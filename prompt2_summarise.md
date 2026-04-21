# autolitsearch — Phase 2: Read, Summarise, and Extract Quotes

> **IMPLEMENTATION NOTE — READ THIS FIRST**
>
> This phase **must be executed by a large language model** (LLM) that genuinely
> reads and comprehends each paper. Do NOT implement this as keyword extraction,
> regex scoring, or any other heuristic that selects sentences without
> understanding them. The required workflow is:
>
> 1. Load the full text of each paper from disk.
> 2. Send the **entire text** in a single prompt to an LLM.
> 3. Ask the LLM to produce `myc_summary` and `direct_quote` based on what it
>    read.
> 4. Write the LLM's response back to `results.csv`.
>
> The recommended implementation uses a local LLM via **Ollama** (model:
> `llama3.1:8b`, which supports a 128 000-token context window — large enough
> for full papers). Install with `curl -fsSL https://ollama.com/install.sh | sh`
> then `ollama pull llama3.1:8b`. Call the model through the Ollama REST API at
> `http://localhost:11434/api/generate`. If the paper text exceeds ~100 000
> tokens, send the Abstract + Methods + Results + Discussion sections only, in
> that order, and note the truncation in the summary.
>
> **A Python keyword-extraction script is not acceptable.** Sentences must be
> understood in context, not selected by token overlap.

Phase 1 has already run. The `papers/` folder contains one subfolder per cell
line, with per-paper subfolders inside each. Each paper subfolder contains
`metadata.json`, `abstract.txt`, and (where available) `fulltext.txt`.
`results.csv` already has one row per paper with search metadata.

Your job now is to loop through every paper, **read the full text** (or the
abstract when full text is unavailable), and add two new columns to `results.csv`:
`myc_summary` and `direct_quote`.

---

## Setup

1. **Read `results.csv`**: Load all rows. This is your work list.
2. **Check for already-processed rows**: If `myc_summary` and `direct_quote`
   columns already exist and are populated for some rows, skip those rows and
   continue from where you left off.
3. **Add output columns**: If `myc_summary` and `direct_quote` do not yet exist
   in `results.csv`, add them (blank) before you begin so the file schema is
   complete.
4. **Confirm and go**: Tell the human how many papers are queued and how many
   (if any) were already processed. Then begin the loop immediately.

---

## The reading loop

LOOP through each unprocessed row in `results.csv`:

### Step 1 — Load the paper text

Locate the paper folder: `papers/<cell_line>/<pmid>/`

- If `fulltext.txt` exists and is non-empty, **use it as your primary source**.
  You MUST read the entire file — introduction, methods, results, discussion,
  and conclusion. Do not skim.
- If `fulltext.txt` does not exist or is empty, fall back to `abstract.txt`.
  Note this in the summary.

Also load `metadata.json` for the paper title, DOI, and `is_free_access` flag.

### Step 2 — Validate relevance (re-triage)

Before extracting information, confirm the paper is still relevant:

1. Does the text mention both the cell line AND a MYC family member
   (MYC, c-MYC, N-MYC, MYCN, L-MYC, MYCL, Myc)?
2. Is the MYC mention substantive — part of actual findings, not just an epitope
   tag or iPSC reprogramming factor list?

If the paper fails re-triage, write `myc_summary = "Discarded: MYC mention not substantive (see notes)"` and `direct_quote = ""`, and move on.

### Step 3 — Deep read and understand

This is the critical step. **You are doing comprehension, not keyword search.**

Read the full text carefully and answer these questions in your head before
writing anything:
- What was the experimental model / what did the authors do with this cell line?
- What did they find about MYC (expression level, amplification, knockdown effect,
  pathway interaction, therapeutic relevance, etc.)?
- What is the main claim of the paper as it relates to MYC and this cell line?

### Step 4 — Write myc_summary

Write a **2–4 sentence summary** in your own words. Be specific and mechanistic.
Good examples:
- "This study showed that c-MYC amplification in COLO-320 cells drives
  extrachromosomal DNA (ecDNA) formation, and that BRD4 binds MYC-containing
  ecDNAs to create phase-separated transcriptional hubs."
- "The authors used siRNA to knock down c-MYC in HT-29 cells and observed
  reduced glycolysis via the SPAG4/c-MYC/SULT2B1 axis."

Bad examples (too vague):
- "This paper studied MYC in cancer cells."
- "MYC was mentioned in the context of this cell line."

If only the abstract was available, begin the summary with: `[Abstract only] ...`

### Step 5 — Extract direct_quote

Find and copy **a verbatim sentence or two** from the paper that most clearly
links MYC to this cell line.

**Rules for quotes:**
- The quote MUST come from text you actually read — do not paraphrase or
  reconstruct it.
- The quote MUST mention the specific cell line (or a clear synonym recognised
  in context) AND a MYC family member.
- **Prefer quotes from the Results or Discussion sections** over the Abstract
  when full text is available. The Abstract is acceptable only when it is the
  only text you have.
- The quote should be the most informative single passage — the sentence that
  most precisely states the finding.
- Copy it exactly, including capitalisation and punctuation.

If you cannot find a verbatim sentence that clearly links MYC and the cell line,
write: `No direct quote available — association inferred from context.` and
explain why in `myc_summary`.

**Never fabricate or paraphrase a quote.**

### Step 6 — Update results.csv

Update the row for this paper in `results.csv`, setting:

| Column        | Value                                           |
|---------------|-------------------------------------------------|
| myc_summary   | Your 2–4 sentence summary (see Step 4)          |
| direct_quote  | Verbatim quote from full text or abstract (Step 5) |
| model_used    | The name/version of the model doing this work   |

Write the updated file after every cell line (not just at the end) so progress
is not lost.

**CSV hygiene**: Wrap fields containing commas or quotes in double-quotes. Escape
internal double-quotes by doubling them (`""`). Use Python's `csv` module or
equivalent.

### Step 7 — Report progress and continue

After finishing a cell line (all its papers), print a one-line status:
```
[3/40] NCIH82 (lung) — 5 papers read, 5 summarised (3 full text, 2 abstract only)
```

Then move immediately to the next cell line. **Do not pause to ask the human.**

---

## Rules

- **Never fabricate quotes.** Every `direct_quote` must be copied verbatim from
  text you actually read. If you cannot find one, say so explicitly.
- **Read the entire full text when it is available.** Do not stop at the abstract
  if `fulltext.txt` exists.
- **Prefer Results/Discussion quotes** over Abstract quotes when full text is
  available.
- **Do not modify any files in `papers/`.** They are read-only input for this phase.
- **Do not re-run PubMed searches.** All data collection was done in Phase 1.

---

## Post-loop summary

When all papers have been processed, print:

```
=== PHASE 2 COMPLETE ===
Total papers processed: X
Papers summarised from full text: X
Papers summarised from abstract only: X
Papers discarded (failed re-triage): X
results.csv is complete and ready.
```

Then tell the human: "All papers read. Summaries and quotes written to results.csv."
