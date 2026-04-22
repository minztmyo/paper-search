#!/usr/bin/env python3
"""
Phase 3: Structured MYC annotation for each paper/cell-line pair.

Reads results.csv, sends each paper to the local LLM, and extracts 9 new
annotation columns per MYC_ANNOTATION_TASK.md.

Output: results2.csv  (all original columns + 9 annotation columns)

Idempotent: reruns skip rows where evidence is already set (unless "LLM_ERROR").
"""

import csv
import json
import re
import sys
import time
from pathlib import Path

import requests

try:
    from json_repair import repair_json as _repair_json
except ImportError:
    _repair_json = None

# ── config ────────────────────────────────────────────────────────────────────
OLLAMA_URL  = "http://localhost:11434/api/generate"
MODEL       = "llama3.1:8b"
HERE        = Path(__file__).parent
PAPERS_DIR  = HERE / "papers"
RESULTS_CSV = HERE / "results.csv"
OUT_CSV     = HERE / "results2.csv"
LOG_FILE    = HERE / "phase3_run.log"

MAX_WORDS  = 90_000
SAVE_EVERY = 10
# ──────────────────────────────────────────────────────────────────────────────

NEW_COLS = [
    "myc_amplified_mentioned",
    "myc_overexpressed_mentioned",
    "myc_dependent_mentioned",
    "experiment_done",
    "myc_overexpression_exp",
    "myc_knockdown",
    "myc_viability_data",
    "evidence",
    "confidence_score",
]

BINARY_COLS  = {"myc_amplified_mentioned", "myc_overexpressed_mentioned",
                "myc_dependent_mentioned"}
TERNARY_COLS = {"experiment_done", "myc_overexpression_exp",
                "myc_knockdown", "myc_viability_data"}

# ── system prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """\
You are a strict, conservative scientific reviewer analyzing cancer biology papers.

Your task: for a given CELL LINE, extract structured YES/NO/NA annotations about
c-MYC (NOT MYCN, NOT MYCL) from the provided paper text.

STRICT RULES:
- Only c-MYC counts. Ignore MYCN and MYCL entirely.
- Use ONLY information explicitly stated in the paper. No external knowledge. No inference.
- Be conservative: if uncertain, answer NO.
- All annotations must be SPECIFIC TO THE NAMED CELL LINE. Ignore data about other cell lines.
- Correlation or association alone does NOT count as evidence of dependence.

DEFINITIONS:

myc_amplified_mentioned (YES/NO):
  YES only if the paper explicitly states MYC genomic amplification, copy number gain,
  or gene amplification IN the named cell line.
  e.g. "40-50 fold amplification of c-MYC", "MYC copy number gain"

myc_overexpressed_mentioned (YES/NO):
  YES only if the paper explicitly states elevated c-MYC mRNA or protein levels
  IN the named cell line.
  e.g. "high MYC expression", "elevated c-Myc protein", "MYC mRNA upregulated"

myc_dependent_mentioned (YES/NO):
  YES only if there is a FUNCTIONAL EXPERIMENT showing reduced cell viability or
  proliferation upon MYC knockdown/knockout/inhibition IN the named cell line.
  Observational statements alone = NO. Correlation alone = NO.
  Must be: perturbation applied → phenotype measured.

experiment_done (YES/NO/NA):
  YES if ANY functional experiment was performed on the named cell line
  (knockdown, overexpression, drug treatment, reporter assay, viability, migration).
  NA if the cell line is only mentioned observationally (no experiments done on it).

myc_overexpression_exp (YES/NO/NA):
  YES only if MYC was artificially increased in the named cell line
  (transfection with MYC vector, ectopic MYC expression, CRISPRa of MYC).
  NA if no MYC overexpression experiment was attempted.

myc_knockdown (YES/NO/NA):
  YES only if MYC was reduced in the named cell line via siRNA, shRNA, or CRISPR KO.
  NA if no MYC knockdown was attempted.

myc_viability_data (YES/NO/NA):
  YES only if cell viability or proliferation was measured after a MYC perturbation
  in the named cell line.
  NA if no MYC viability/proliferation experiment was performed.

evidence (string):
  Verbatim quote of ≤25 words from the paper directly supporting the strongest YES
  annotation. If there are no YES annotations: "NA".

confidence_score (integer 0–100):
  How confident you are in the full set of annotations for this cell line.
  90–100: definitive, explicit text.
  70–89: strong evidence, minor ambiguity.
  50–69: moderate, some inference needed.
  0–49: uncertain.

OUTPUT FORMAT — a JSON object with EXACTLY these 9 keys. No extra keys.

Example of correct output:
{"myc_amplified_mentioned": "NO", "myc_overexpressed_mentioned": "NO", "myc_dependent_mentioned": "YES", "experiment_done": "YES", "myc_overexpression_exp": "NO", "myc_knockdown": "YES", "myc_viability_data": "YES", "evidence": "c-Myc knockdown in MDA-MB-231 resulted in 60% reduction in proliferation", "confidence_score": 95}

Output ONLY the JSON object. No preamble. No explanation. No markdown fences.
"""
# ──────────────────────────────────────────────────────────────────────────────


def load_csv(path: Path) -> tuple[list[dict], list[str]]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        rows = [dict(r) for r in reader]
    return rows, fieldnames


def save_output(rows: list[dict], fieldnames: list[str]) -> None:
    tmp = OUT_CSV.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(OUT_CSV)


def load_paper_text(cell_line: str, pmid: str) -> tuple[str, str]:
    base = PAPERS_DIR / cell_line / pmid
    ft = base / "fulltext.txt"
    ab = base / "abstract.txt"
    if ft.exists() and ft.stat().st_size > 200:
        return ft.read_text(encoding="utf-8", errors="replace"), "fulltext"
    if ab.exists():
        return ab.read_text(encoding="utf-8", errors="replace"), "abstract"
    return "", "missing"


def truncate_to_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "\n\n[... text truncated ...]"


def _parse_annotation(data: dict) -> dict:
    """Validate and normalise the LLM's annotation dict into the expected schema."""
    result = {}
    for col in NEW_COLS:
        if col in BINARY_COLS:
            val = str(data.get(col, "")).strip().upper()
            result[col] = val if val in {"YES", "NO"} else "NO"
        elif col in TERNARY_COLS:
            val = str(data.get(col, "")).strip().upper()
            result[col] = val if val in {"YES", "NO", "NA"} else "NA"
        elif col == "confidence_score":
            try:
                score = int(str(data.get(col, 0)).strip())
                result[col] = str(max(0, min(100, score)))
            except (ValueError, TypeError):
                result[col] = "0"
        else:  # evidence
            result[col] = str(data.get(col, "NA")).strip()
    return result


def ask_llm(cell_line: str, text: str, source: str) -> dict:
    """Send paper text to ollama, return parsed annotation dict."""
    truncated = truncate_to_words(text, MAX_WORDS)
    user_msg = (
        f"Cell line: {cell_line}\n\n"
        f"--- PAPER TEXT ({source}) ---\n\n"
        f"{truncated}\n\n"
        f"--- END OF PAPER ---\n\n"
        f"Annotate ONLY the cell line '{cell_line}' named above. "
        f"Output ONLY the JSON object with the 9 required keys."
    )
    payload = {
        "model": MODEL,
        "system": SYSTEM_PROMPT,
        "prompt": user_msg,
        "stream": False,
        "options": {
            "temperature": 0.05,
            "num_predict": 700,
        },
    }
    raw = ""
    for attempt in range(4):
        try:
            resp = requests.post(OLLAMA_URL, json=payload, timeout=300)
            resp.raise_for_status()
            raw = resp.json().get("response", "")
            # Strip markdown fences
            raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
            raw = re.sub(r"\s*```$", "", raw.strip())
            # Truncation repair: close open string + object
            work = raw
            if "{" in work and "}" not in work:
                work = re.sub(r'"([^"]*?)$', r'"\1..."', work.rstrip()) + "}"
            m = re.search(r"\{.*\}", work, re.DOTALL)
            if not m:
                raise json.JSONDecodeError("No JSON found", work, 0)
            json_str = m.group(0)
            # Strip illegal ASCII control chars
            json_str = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", json_str)
            # Parse with json_repair fallback
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                if _repair_json is not None:
                    data = json.loads(_repair_json(json_str))
                else:
                    raise
            if isinstance(data, list):
                data = data[0] if data else {}
            return _parse_annotation(data)
        except (json.JSONDecodeError, requests.RequestException) as e:
            log(f"  attempt {attempt+1} failed: {e!r}  raw={raw[:100]!r}")
            if attempt < 3:
                time.sleep(5 * (attempt + 1))
    # Total failure sentinel
    result = {c: "NO" for c in BINARY_COLS}
    result.update({c: "NA" for c in TERNARY_COLS})
    result["evidence"] = "LLM_ERROR"
    result["confidence_score"] = "0"
    return result


def log(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def check_ollama() -> None:
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=5)
        r.raise_for_status()
        models = [m["name"] for m in r.json().get("models", [])]
        log(f"Ollama running. Available models: {models}")
        if not any(MODEL in m for m in models):
            log(f"WARNING: {MODEL} not found — pull it with: ollama pull {MODEL}")
    except Exception as e:
        log(f"ERROR: Cannot reach ollama: {e}")
        log("Start ollama with:  ollama serve")
        sys.exit(1)


def main() -> None:
    check_ollama()

    # Load source data
    src_rows, src_fieldnames = load_csv(RESULTS_CSV)

    # Build output fieldnames: original cols + new annotation cols
    out_fieldnames = src_fieldnames + [c for c in NEW_COLS if c not in src_fieldnames]

    # Load existing results2.csv if present (for idempotent reruns)
    existing: dict[str, dict] = {}
    if OUT_CSV.exists():
        ex_rows, _ = load_csv(OUT_CSV)
        for r in ex_rows:
            key = f"{r.get('cell_line', '')}|{r.get('pmid', '')}"
            existing[key] = r

    # Build working row list: start from source, overlay any existing annotations
    out_rows: list[dict] = []
    for r in src_rows:
        key = f"{r.get('cell_line', '')}|{r.get('pmid', '')}"
        if key in existing:
            out_rows.append(existing[key])
        else:
            row = dict(r)
            for c in NEW_COLS:
                row.setdefault(c, "")
            out_rows.append(row)

    # Rows that need annotation: real PMID + evidence not yet set (or LLM_ERROR retry)
    todo = []
    for i, row in enumerate(out_rows):
        pmid = row.get("pmid", "").strip()
        if pmid in ("", "NA", "ERROR"):
            continue
        evidence = row.get("evidence", "").strip()
        # Skip if already annotated successfully
        if evidence and evidence != "LLM_ERROR":
            continue
        todo.append(i)

    log(f"Total rows in results.csv : {len(src_rows)}")
    log(f"Rows to annotate          : {len(todo)}")
    log("")

    # Write initial output file so it exists for checkpointing
    save_output(out_rows, out_fieldnames)

    done = 0
    for batch_i, row_i in enumerate(todo):
        row = out_rows[row_i]
        cell_line = row["cell_line"]
        pmid      = row["pmid"]
        title     = row.get("paper_title", "")[:60]

        text, source = load_paper_text(cell_line, pmid)
        if not text:
            log(f"[{batch_i+1}/{len(todo)}] SKIP (no text) {cell_line} / {pmid}")
            for c in BINARY_COLS:
                row[c] = "NO"
            for c in TERNARY_COLS:
                row[c] = "NA"
            row["evidence"] = "NA"
            row["confidence_score"] = "0"
            out_rows[row_i] = row
            continue

        word_count = len(text.split())
        log(f"[{batch_i+1}/{len(todo)}] {cell_line} / PMID {pmid} / {source} / {word_count} words")
        log(f"  Title: {title}")

        ann = ask_llm(cell_line, text, source)
        for col, val in ann.items():
            row[col] = val
        out_rows[row_i] = row

        amp  = ann["myc_amplified_mentioned"]
        oe   = ann["myc_overexpressed_mentioned"]
        dep  = ann["myc_dependent_mentioned"]
        exp  = ann["experiment_done"]
        kd   = ann["myc_knockdown"]
        conf = ann["confidence_score"]
        log(f"  amp={amp} oe={oe} dep={dep} exp={exp} kd={kd} conf={conf}")

        done += 1
        if done % SAVE_EVERY == 0:
            save_output(out_rows, out_fieldnames)
            log(f"  [checkpoint] saved {done} annotations so far")

    save_output(out_rows, out_fieldnames)
    log(f"\nDone. Annotated {done} papers.")
    log(f"Output: {OUT_CSV}")


if __name__ == "__main__":
    main()
