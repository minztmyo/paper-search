# Technical Notes — autolitsearch pipeline

## Overview

Two-phase Python pipeline: Phase 1 searches PubMed and downloads papers,
Phase 2 runs a local LLM over every paper to extract MYC biology summaries.
No external APIs are used in Phase 2; all inference is on-device via ollama.

---

## Environment

| Component | Version / Detail |
|---|---|
| Python | 3.12.3 (conda base) |
| OS | Linux (Ubuntu), GTX 1070 + GTX 1080 |
| Ollama | local service via systemd, `http://localhost:11434` |
| LLM | `llama3.1:8b` (4.9 GB, 128k context window) |
| Key Python packages | requests, beautifulsoup4, lxml, pypdf, json-repair |

Ollama was installed via `curl -fsSL https://ollama.com/install.sh | sh` and
registered as a systemd service.  The model was pulled with `ollama pull llama3.1:8b`.

---

## Phase 1 — `phase1_search.py`

### Input
`cell_lines.csv` — 390 cell lines across four tissues: lung (207), colorectal
(70), breast (61), pancreas (52).

### Algorithm

1. **Name variant expansion** — `cell_line_variants()` generates hyphen/dash
   permutations for common naming conventions (NCI-H*, MDA-MB-*, RERF-LC-*,
   MSTO-*, COR-L*, LCLC-*).  All variants are OR-ed into the PubMed query.

2. **PubMed query** — NCBI ESearch with:
   ```
   ("<cell-line-variant1>" OR ...) AND
   (MYC OR c-MYC OR "MYC amplification" OR "MYC-driven" OR
    "N-MYC" OR MYCN OR "L-MYC" OR MYCL)
   ```
   Up to 20 results per cell line, sorted by relevance.

3. **Abstract triage** — Every abstract is fetched via EFetch.  Papers are
   dropped if:
   - No MYC family regex match (`\b(c-?MYC|MYCN|N-?MYC|MYCL|L-?MYC|Myc)\b`)
   - Matches false-positive patterns (Myc-tag, c-Myc epitope tag, iPSC
     reprogramming factors)

4. **Full-text download** — For papers with a PMCID, the PMC FTP XML is
   fetched and parsed with `xml.etree.ElementTree`.  Text is written to
   `papers/<cell_line>/<pmid>/fulltext.txt`.  Abstract is always saved to
   `abstract.txt`.  A `metadata.json` is written alongside.

5. **Rate limiting** — 0.4 s between NCBI API calls; exponential backoff on
   HTTP 429 (up to 6 retries, doubling delay).

### Output
- `papers/` — 137 cell-line subdirectories, 852 paper folders on disk
- `results.csv` — one row per accepted paper (873 real rows + header rows for
  cell lines with 0 papers), columns:
  `cell_line, tissue, pmid, pmcid, paper_title, is_free_access, paper_url, search_timestamp`

---

## Phase 2 — `phase2_llm.py`

### Design principle
Full paper text is sent verbatim to the LLM.  No keyword extraction, no
regex scoring, no heuristics.  The LLM reads the text and writes the summary.

### Algorithm

1. **Load** `results.csv`; select rows where `myc_summary` is empty or
   `"LLM_ERROR"` (enables idempotent reruns / retries).

2. **Text loading** — prefer `fulltext.txt` (if > 200 bytes) over
   `abstract.txt`.  Text is word-capped at 90,000 words to stay within the
   128k-token context window.

3. **LLM call** — POST to `http://localhost:11434/api/generate`:
   - `temperature: 0.1` (near-deterministic)
   - `num_predict: 1200`
   - System prompt instructs JSON-only output with exactly two keys:
     `myc_summary` and `direct_quote`, with a concrete example

4. **JSON parsing pipeline** (robust to common LLM failures):
   - Strip markdown code fences
   - If response contains `{` but no `}` (truncated), close the open string
     and append `}`
   - Extract first `{...}` block via regex
   - Strip ASCII control chars `\x00–\x08`, `\x0b`, `\x0c`, `\x0e–\x1f`
     (LLM occasionally embeds raw control chars inside string values)
   - `json.loads()` strict parse; on failure, fall back to `json_repair`
     (handles unescaped internal quotes)
   - If LLM returns a list, unwrap `data[0]`
   - `_extract_fields()` tries canonical key names then falls back
     positionally (handles LLM inventing custom key names)

5. **Retry** — 4 attempts per paper with 5/10/15 s backoff.  Papers that
   fail all 4 attempts are written as `"LLM_ERROR"` and retried on the next
   script invocation.

6. **Checkpoint** — `results.csv` is written atomically (write to `.tmp`,
   then `rename`) every 10 papers.

### Output columns added to `results.csv`
| Column | Content |
|---|---|
| `myc_summary` | 2–4 sentence mechanistic description of MYC's role in the specific cell line, from the paper |
| `direct_quote` | Verbatim sentence from Results/Discussion mentioning both cell line and MYC |
| `model_used` | `llama3.1:8b` (or `manual` for one hand-patched row) |

### Final stats
| Metric | Count |
|---|---|
| Papers processed | 873 |
| Fulltext summaries | 513 |
| Abstract-only summaries | 360 |
| LLM_ERROR remaining | 0 |
| Hand-patched rows | 1 (MIAPACA2 / PMID 23486104 — LLM consistently produced malformed JSON due to embedded `"` in its output; summary written from abstract) |

---

## File layout

```
paper-search/
├── cell_lines.csv          input: 390 cell lines
├── phase1_search.py        Phase 1 script
├── phase2_llm.py           Phase 2 script
├── results.csv             master output (1137 rows incl. header/empty rows)
├── papers/                 downloaded texts (137 cell line dirs, 852 paper dirs)
│   └── <CELL_LINE>/
│       └── <PMID>/
│           ├── abstract.txt
│           ├── fulltext.txt   (when PMC full text available)
│           └── metadata.json
├── phase1_run.log
├── phase2_run.log
├── prompt1_search.md       spec for Phase 1
└── prompt2_summarise.md    spec for Phase 2
```

---

## Reproducing the run

```bash
# Prerequisites: ollama running with llama3.1:8b pulled
ollama pull llama3.1:8b

# Phase 1 (approx. 2–3 hours, rate-limited by NCBI)
python phase1_search.py

# Phase 2 (approx. 4–6 hours on CPU/GPU depending on hardware)
python phase2_llm.py
# Rerunnable: skips already-processed rows, retries LLM_ERROR rows
```

---

## Known limitations

- NCBI ESearch relevance ranking is used, capped at 20 papers per cell line.
  Some highly relevant papers may be missed if PubMed ranks them below rank 20.
- Full text is only available for PMC Open Access papers.  360 summaries are
  therefore based on abstracts only and are marked `[Abstract only]`.
- `llama3.1:8b` occasionally hallucinates pathway details not present in the
  paper.  Direct quotes serve as a ground-truth anchor but should be
  spot-checked.
- One paper (MIAPACA2 / PMID 23486104) was hand-summarised because the LLM
  consistently produced JSON with an unescaped internal double-quote that
  could not be repaired automatically across 4×4 retry attempts.
