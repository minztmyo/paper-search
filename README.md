# MYC Literature Search — Results Guide

## What this is

An automated literature search that asked PubMed: *"For each of these cancer
cell lines, what do published papers say about MYC's role?"*

The search covered **390 cell lines** across four tissue types — lung (207),
colorectal (70), breast (61), and pancreas (52) — and returned summaries for
**873 papers**.

---

## What is in `results.csv`

Open `results.csv` in Excel or any spreadsheet tool.  Each row is one paper.

| Column | What it contains |
|---|---|
| `cell_line` | Cell line name (e.g. A549, HCC827, MCF7) |
| `tissue` | Tissue of origin (lung / colorectal / breast / pancreas) |
| `pmid` | PubMed ID — paste into https://pubmed.ncbi.nlm.nih.gov/ to open the paper |
| `pmcid` | PubMed Central ID (if available) |
| `paper_title` | Full title of the paper |
| `is_free_access` | Whether the full paper text was freely available |
| `paper_url` | Direct link to the paper |
| `search_timestamp` | When this paper was collected |
| `myc_summary` | **2–4 sentence summary of what the paper says about MYC in this cell line** |
| `direct_quote` | A verbatim sentence from the paper mentioning both the cell line and MYC |
| `model_used` | Which AI model wrote the summary |

### Important notes on the summaries

- Every summary was written by an AI (llama3.1:8b) that **read the actual
  paper text** — not keywords or metadata.
- Summaries marked **`[Abstract only]`** were generated from the abstract
  because the full paper text was not freely available.  These are less
  detailed but still based on the published abstract.
- The `direct_quote` column gives you a verbatim sentence to verify the
  summary against.  If a summary seems surprising, use the quote as a
  starting point to locate the relevant passage in the paper.
- The AI was instructed not to invent information.  However, as with any AI
  tool, factual errors are possible, particularly for nuanced mechanistic
  claims.  **Treat summaries as a first-pass triage, not as ground truth.**

---

## How to use the results

### Finding papers for a specific cell line

Filter column `cell_line` for your cell line of interest.  For example,
filtering for `A549` will show all papers found for that lung cancer cell line.

### Comparing across cell lines in a tissue

Filter column `tissue` for your tissue of interest to see all cell lines and
their associated MYC papers side by side.

### Going to the source

Click the URL in `paper_url`, or search the PMID at
https://pubmed.ncbi.nlm.nih.gov/ to read the original paper.

### Spot-checking a summary

Search the `direct_quote` text in the original paper (Ctrl+F in the PDF).
This brings you directly to the relevant passage.

---

## Coverage and limitations

**What was searched:**
Every cell line was searched on PubMed for papers co-mentioning that cell
line and any member of the MYC family (c-MYC, MYCN/N-MYC, MYCL/L-MYC).
Up to 20 papers per cell line were collected.

**What may be missing:**
- Papers ranked below position 20 in PubMed relevance are not included.
- Papers behind paywalls that are not in PubMed Central were summarised from
  abstracts only.
- A small number of cell lines returned zero papers — meaning no
  MYC-related papers were found on PubMed for that cell line.

**What was excluded:**
Papers were automatically filtered out if they appeared to be about:
- Myc-tag (a molecular biology tag unrelated to MYC biology)
- iPSC reprogramming protocols (which mention Myc as a Yamanaka factor,
  not in a cancer context)

**Numbers at a glance:**

| | Count |
|---|---|
| Cell lines searched | 390 |
| Cell lines with ≥ 1 paper found | 137 |
| Papers collected | 873 |
| Summaries from full text | 513 |
| Summaries from abstract only | 360 |

---

## Questions?

For questions about the biology or the search scope, review
`prompt2_summarise.md` for the exact instructions given to the AI.
For technical questions about how the pipeline works, see `TECHNICAL_NOTES.md`.
