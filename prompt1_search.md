# autolitsearch — Phase 1: Search, Filter, and Collect

Your job in this phase is to search PubMed for papers linking each cell line to
MYC-driven cancer biology, triage the results, download available full texts, and
organise everything on disk. **Do not summarise or quote papers yet.** That comes
in Phase 2.

---

## Setup

1. **Locate the input file**: Read `cell_lines.csv` in the working directory. It
   contains one cell line name per line, optionally followed by a tab and tissue
   type (e.g. `MDA-MB-231\tbreast`). Blank lines and lines starting with `#` are
   ignored.

2. **Create the output folder**: Create a folder called `papers/` in the working
   directory if it does not already exist. For each cell line you process, you will
   create a subfolder inside `papers/` named after the standardised cell line name
   (e.g. `papers/NCIH82/`, `papers/MDA-MB-231/`).

3. **Initialise results.csv**: If `results.csv` does not already exist, create it
   with the following header row:

   ```
   cell_line,tissue,pmid,pmcid,paper_title,is_free_access,paper_url,search_timestamp
   ```

   Note: `myc_summary`, `direct_quote`, and `model_used` columns are intentionally
   absent here — they will be added in Phase 2.

4. **Read existing results**: If `results.csv` already exists, read it to know
   which cell lines have already been processed. Do not re-process them unless
   asked.

5. **Confirm and go**: Tell the human how many cell lines are queued and how many
   (if any) were already processed. Then begin the loop immediately.

---

## The search and collection loop

LOOP through each unprocessed cell line in `cell_lines.csv`:

### Step 1 — Search PubMed

Use the NCBI E-utilities API (no API key required for moderate use) to search
for papers linking the cell line to MYC. Build the query carefully:

- Include common name variants of the cell line. For example, for `MDAMB231`
  also search `"MDA-MB-231"`. For `NCIH460` also search `"NCI-H460"` and `"H460"`.
- Combine with MYC terms:
  `(cell_line_variants) AND (MYC OR c-MYC OR "MYC amplification" OR "MYC-driven" OR N-MYC OR MYCN OR L-MYC OR MYCL)`
- Request up to 20 results per cell line (`retmax=20`), sorted by relevance.
- Use the esearch endpoint:
  `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=QUERY&retmode=json&retmax=20&sort=relevance`

Collect the returned PMIDs.

**Rate limiting**: Wait at least 0.4 seconds between every API call to respect
NCBI's usage policy (max ~3 req/s without an API key).

### Step 2 — Fetch article metadata

For each batch of PMIDs, use the efetch endpoint to retrieve titles, abstracts,
PMCIDs, and DOIs:
`https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=PMID1,PMID2,...&retmode=xml`

Parse each `<PubmedArticle>` for:
- PMID
- PMCID (from `<ArticleId IdType="pmc">`)
- ArticleTitle
- AbstractText (may have multiple labelled sections — concatenate them)
- DOI (from `<ELocationID EIdType="doi">`)

### Step 3 — Triage abstracts

Before spending time on full-text download, quickly triage each abstract:

1. Does the abstract mention both the cell line AND a MYC family member
   (MYC, c-MYC, N-MYC, MYCN, L-MYC, MYCL, Myc)?
2. Is the mention substantive — i.e., MYC is part of the actual findings or
   hypothesis, not just a reprogramming factor for iPSCs or an epitope tag?

**Discard** papers that fail triage. Common false-positive patterns to filter out:
- "Myc-tagged" / "c-Myc epitope tag" — immunoprecipitation tagging, not oncogene
- "c-MYC, KLF4, OCT4, SOX2" in context of iPSC reprogramming
- Cell line name substring collisions (e.g., "PK1" matching "LLC-PK1")
- Generic reviews that mention the cell line only in a supplementary table

**Keep** a paper if:
- The study uses the specific cell line (not just mentions it in a list).
- MYC (or a family member) is a meaningful part of the study — as a target,
  biomarker, pathway component, or therapeutic axis.

### Step 4 — Attempt full-text download

For each paper that passes triage, attempt to download the full text. Work through
the following options in order:

1. **PubMed Central (PMC)**: If a PMCID is available, fetch the full article XML
   using the BioC JSON endpoint (clean sectioned text, preferred):
   `https://www.ncbi.nlm.nih.gov/research/bioxcel/fetch/?pmcid=PMC1234567`
   Or fall back to the standard efetch XML:
   `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id=PMC1234567&rettype=full&retmode=xml`
   Extract the article body text from the XML/HTML.

2. **bioRxiv / medRxiv preprints**: If the DOI starts with `10.1101/`, download
   the full text from:
   `https://www.biorxiv.org/content/DOI.full` or
   `https://www.medrxiv.org/content/DOI.full`
   If only a PDF is available, extract text from the PDF.

3. **Publisher open access**: For other open-access papers, try the DOI link
   directly and download the HTML or PDF from the publisher site.

4. **Abstract only**: If none of the above succeed, the paper is **not free
   access**. Save only the abstract text.

### Step 5 — Save files to disk

For each paper that passes triage, create a subfolder:
`papers/<CELL_LINE_NAME>/<PMID>/`

Inside that subfolder, save:
- `abstract.txt` — the plain-text abstract (always)
- `fulltext.txt` — the extracted full text, if successfully downloaded
- `metadata.json` — a JSON file with the fields:
  ```json
  {
    "cell_line": "...",
    "tissue": "...",
    "pmid": "...",
    "pmcid": "...",
    "paper_title": "...",
    "doi": "...",
    "is_free_access": true,
    "paper_url": "https://pubmed.ncbi.nlm.nih.gov/PMID/"
  }
  ```

### Step 6 — Append to results.csv

Append one row per validated paper to `results.csv`:

| Column           | Description                                                    |
|------------------|----------------------------------------------------------------|
| cell_line        | Standardised name from `cell_lines.csv`                        |
| tissue           | Tissue type (breast, colon, lung, etc.)                        |
| pmid             | PubMed ID (numeric)                                            |
| pmcid            | PubMed Central ID (e.g. `PMC1234567`), or blank if none        |
| paper_title      | Full title of the paper                                        |
| is_free_access   | `yes` if full text was downloaded, `no` if abstract only       |
| paper_url        | `https://pubmed.ncbi.nlm.nih.gov/PMID/`                       |
| search_timestamp | ISO 8601 timestamp of when the search was performed            |

**CSV hygiene**: Wrap fields containing commas or quotes in double-quotes. Escape
internal double-quotes by doubling them (`""`). Use Python's `csv` module or
equivalent to handle this correctly.

**Edge cases**:
- **Zero results for a cell line**: Append a single row with `pmid=NA`,
  `paper_title=No MYC-related papers found`, `is_free_access=NA`, and leave
  other fields blank. This records that the cell line was searched, not skipped.
- **Retracted papers**: Add `[RETRACTED]` to the `paper_title`. Still include
  if the scientific content is informative.
- **Preprints**: Add `[PREPRINT]` to the `paper_title`.
- **Non-English papers**: Include if the abstract is in English.

### Step 7 — Report progress and continue

After finishing a cell line, print a one-line status:
```
[3/40] NCIH82 (lung) — 8 papers found, 5 passed triage, 3 with full text
```

Then move immediately to the next cell line. **Do not pause to ask the human.**

---

## Rules

- **Do not hallucinate PMIDs, titles, or any metadata.** Every PMID must come
  from an actual PubMed API response.
- **Do not modify `cell_lines.csv`.** It is read-only input.
- **Do not scrape paywalled content.** If a paper is behind a paywall, save only
  the abstract and mark `is_free_access=no`.
- **Stay under NCBI rate limits.** Wait ≥0.4 s between API calls without an API key.
- **Do not summarise or quote papers yet.** All extraction and synthesis happens
  in Phase 2.

---

## Post-loop summary

When all cell lines have been processed, print:

```
=== PHASE 1 COMPLETE ===
Total cell lines searched: X
Cell lines with MYC papers: X
Cell lines with no MYC papers: X
Total papers in results.csv: X
Papers with full text: X
Papers with abstract only: X
papers/ folder ready for Phase 2.
```
