"""
Phase 2: Real LLM reading of each paper using ollama + llama3.1:8b.

For every row in results.csv that has a real PMID and an empty myc_summary,
the script reads the full text (or abstract if no full text) and sends it
entirely to the local LLM.  The LLM writes:
  - myc_summary : 2-4 sentence mechanistic description of MYC's role in
                  this specific cell line, based on what is actually written
                  in the paper.
  - direct_quote: a verbatim sentence from the Results or Discussion section
                  that mentions both the cell line and MYC/c-MYC/MYCN.

No keyword extraction.  No heuristics.  The LLM reads the text.
"""

import csv
import json
import os
import re
import sys
try:
    from json_repair import repair_json as _repair_json
except ImportError:
    _repair_json = None
import time
from pathlib import Path

import requests

# ── config ────────────────────────────────────────────────────────────────────
OLLAMA_URL  = "http://localhost:11434/api/generate"
MODEL       = "llama3.1:8b"
HERE        = Path(__file__).parent
PAPERS_DIR  = HERE / "papers"
RESULTS_CSV = HERE / "results.csv"
LOG_FILE    = HERE / "phase2_run.log"

# llama3.1:8b has a 128k-token context; keep ~90k words to stay safe
MAX_WORDS   = 90_000
# ──────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a cancer biology literature analyst.

You will be given a research paper and a cell line name.
Read the entire text carefully.  Then output ONLY a JSON object with \
exactly these two string keys — no other keys, no nesting, no arrays:

  "myc_summary"  : 2–4 sentences describing what the paper says about how \
MYC (c-MYC, MYCN, N-MYC, L-MYC, or any MYC family member) functions in the \
named cell line.  Include genes, pathways, and experimental evidence mentioned \
in the paper.  Use ONLY information from the paper; do not guess.
  "direct_quote" : Copy one sentence verbatim from the Results or Discussion \
section that mentions both the cell line name and MYC.  If no exact match, \
use the closest sentence from any section.  Copy character-for-character.

If the paper does not actually discuss MYC in the context of the named cell \
line, set myc_summary to "MYC not discussed for this cell line in this paper" \
and direct_quote to "".

Example of correct output:
{"myc_summary": "In HCC827 cells, TSA treatment reduced c-Myc protein levels by 60%.", "direct_quote": "TSA dramatically downregulated BET expression, as well as that of c-Myc."}

Output ONLY the JSON object.  No preamble.  No explanation.  No markdown.
"""


def load_results():
    rows = []
    with open(RESULTS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames[:]
        for row in reader:
            rows.append(dict(row))
    return rows, fieldnames


def save_results(rows, fieldnames):
    tmp = RESULTS_CSV.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(RESULTS_CSV)


def load_paper_text(cell_line: str, pmid: str) -> tuple[str, str]:
    """Return (text, source) where source is 'fulltext' or 'abstract'."""
    base = PAPERS_DIR / cell_line / pmid
    ft = base / "fulltext.txt"
    ab = base / "abstract.txt"
    if ft.exists() and ft.stat().st_size > 200:
        text = ft.read_text(encoding="utf-8", errors="replace")
        return text, "fulltext"
    if ab.exists():
        text = ab.read_text(encoding="utf-8", errors="replace")
        return text, "abstract"
    return "", "missing"


def truncate_to_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "\n\n[... text truncated at word limit ...]"


# Candidate key names the LLM might use for the summary field
_SUMMARY_KEYS = (
    "myc_summary", "MYC_summary", "summary", "myc_role", "MYC_role",
    "myc_description", "description", "mechanistic_summary",
)
# Candidate key names for the quote field
_QUOTE_KEYS = (
    "direct_quote", "quote", "verbatim_quote", "Direct_Quote",
    "direct_sentence", "relevant_sentence",
)


def _extract_fields(data: dict) -> tuple[str, str]:
    """Pull myc_summary and direct_quote from a dict regardless of key names."""
    # Try canonical keys first
    for k in _SUMMARY_KEYS:
        if k in data and isinstance(data[k], str):
            summary = data[k]
            break
    else:
        # Fall back: first string value in the dict
        summary = next(
            (v for v in data.values() if isinstance(v, str) and len(v) > 10), ""
        )

    for k in _QUOTE_KEYS:
        if k in data and isinstance(data[k], str):
            quote = data[k]
            break
    else:
        # Fall back: second distinct string value
        strings = [v for v in data.values() if isinstance(v, str) and v != summary]
        quote = strings[0] if strings else ""

    return summary, quote


def ask_llm(cell_line: str, text: str, source: str) -> dict:
    """Send paper text to ollama and return parsed dict with myc_summary/direct_quote."""
    truncated = truncate_to_words(text, MAX_WORDS)
    user_msg = (
        f"Cell line: {cell_line}\n\n"
        f"--- PAPER TEXT ({source}) ---\n\n"
        f"{truncated}\n\n"
        f"--- END OF PAPER ---\n\n"
        f'Output a JSON object with exactly two string keys: \'myc_summary\' and \'direct_quote\'.'
    )
    payload = {
        "model": MODEL,
        "system": SYSTEM_PROMPT,
        "prompt": user_msg,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 1200,
        },
    }
    raw = ""
    for attempt in range(4):
        try:
            resp = requests.post(OLLAMA_URL, json=payload, timeout=300)
            resp.raise_for_status()
            raw = resp.json().get("response", "")
            # Strip markdown code fences if present
            raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
            raw = re.sub(r"\s*```$", "", raw.strip())
            # Extract first JSON object from the response (handles preamble text)
            # If the response is truncated (no closing }), repair it first
            work = raw
            if '{' in work and '}' not in work:
                # Close any open string then close the object
                work = re.sub(r'"([^"]*?)$', r'"\1..."', work.rstrip()) + '}'
            m = re.search(r'\{.*\}', work, re.DOTALL)
            if not m:
                raise json.JSONDecodeError("No JSON object found", work, 0)
            json_str = m.group(0)
            # Strip ALL ASCII control chars (0x00-0x1F) except \t \n \r
            json_str = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', json_str)
            # Try strict parse, then fall back to json_repair for unescaped quotes etc.
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                if _repair_json is not None:
                    repaired = _repair_json(json_str)
                    data = json.loads(repaired)
                else:
                    raise
            # If LLM wrapped in a list, unwrap
            if isinstance(data, list):
                data = data[0] if data else {}
            summary, quote = _extract_fields(data)
            if not summary:
                log(f"  [WARN] could not extract summary. raw={raw[:200]!r}")
            return {"myc_summary": summary, "direct_quote": quote}
        except (json.JSONDecodeError, requests.RequestException) as e:
            log(f"  attempt {attempt+1} failed: {e!r}  raw={raw[:120]!r}")
            if attempt < 3:
                time.sleep(5 * (attempt + 1))
    return {"myc_summary": "LLM_ERROR", "direct_quote": ""}

def log(msg: str):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def check_ollama():
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=5)
        r.raise_for_status()
        models = [m["name"] for m in r.json().get("models", [])]
        log(f"Ollama is running. Available models: {models}")
        if not any(MODEL in m for m in models):
            log(f"WARNING: {MODEL} not found in model list!")
    except Exception as e:
        log(f"ERROR: Cannot reach ollama at {OLLAMA_URL}: {e}")
        log("Make sure ollama is running:  ollama serve")
        sys.exit(1)


def main():
    check_ollama()

    rows, fieldnames = load_results()

    # Rows that need processing: real PMID and empty myc_summary
    todo = [
        (i, r) for i, r in enumerate(rows)
        if r.get("pmid", "").strip() not in ("NA", "ERROR", "")
        and (
            not r.get("myc_summary", "").strip()
            or r.get("myc_summary", "").strip() == "LLM_ERROR"
        )
    ]

    log(f"Total rows in results.csv : {len(rows)}")
    log(f"Rows to process           : {len(todo)}")
    log("")

    save_every = 10   # write CSV after every N papers
    done = 0
    errors = 0

    for idx, (row_i, row) in enumerate(todo):
        cell_line = row["cell_line"]
        pmid      = row["pmid"]
        title     = row.get("paper_title", "")[:60]

        text, source = load_paper_text(cell_line, pmid)
        if not text:
            log(f"[{idx+1}/{len(todo)}] SKIP (no text on disk) {cell_line}/{pmid}")
            row["myc_summary"]  = "NO_TEXT_ON_DISK"
            row["direct_quote"] = ""
            row["model_used"]   = MODEL
            rows[row_i] = row
            errors += 1
            continue

        word_count = len(text.split())
        log(f"[{idx+1}/{len(todo)}] {cell_line} / PMID {pmid} / {source} / {word_count} words")
        log(f"  Title: {title}")

        result = ask_llm(cell_line, text, source)

        summary = result.get("myc_summary", "").strip()
        quote   = result.get("direct_quote", "").strip()

        if source == "abstract":
            summary = f"[Abstract only] {summary}"

        row["myc_summary"]  = summary
        row["direct_quote"] = quote
        row["model_used"]   = MODEL
        rows[row_i] = row

        log(f"  Summary: {summary[:120]}")
        log(f"  Quote  : {quote[:100]}")
        log("")

        done += 1
        if done % save_every == 0:
            save_results(rows, fieldnames)
            log(f"  [checkpoint] saved {done} papers so far")

    # Final save
    save_results(rows, fieldnames)
    log(f"Done. Processed {done} papers, {errors} errors/skips.")
    log(f"Results written to {RESULTS_CSV}")


if __name__ == "__main__":
    main()
