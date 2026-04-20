# autolitsearch

Autonomous agentic literature search: given a list of cell lines, find and deeply
read research papers linking each cell line to MYC-driven cancer biology. You're going to extract information from
the biomedical literature, one cell line at a time.

## Setup

To set up a new search session:

1. **Locate the input file**: Read `cell_lines.csv` in the working directory. This
   file contains one cell line name per line, optionally followed by a tab and tissue
   type (e.g. `MDA-MB-231\tbreast`). Blank lines and lines starting with `#` are
   ignored.
2. **Initialize results.csv**: If `results.csv` does not already exist, create it
   with the following header row:

   ```
   cell_line,tissue,pmid,pmcid, paper_title,is_free_access,paper_url,myc_summary,direct_quote,search_time, model_used
   ```

3. **Read existing results**: If `results.csv` already exists, read it to know
   which cell lines have already been searched. Do not re-search them unless the
   human asks you to.
4. **Confirm and go**: Tell the human how many cell lines are queued, how many
   (if any) were already searched, and begin the loop.

## The search loop

LOOP through each unsearched cell line in `cell_lines.txt`:

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

### Step 2 — Fetch article metadata

For each batch of PMIDs, use the efetch endpoint to get titles and abstracts:
`https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=PMID1,PMID2,...&retmode=xml`

Parse each `<PubmedArticle>` for:
- PMID
- ArticleTitle
- AbstractText (may have multiple sections)
- DOI (from `<ELocationID EIdType="doi">`)

**Rate limiting**: Wait at least 0.4 seconds between API calls to respect NCBI's
usage policy. If you have an API key, you may go faster (10 req/s).

### Step 3 — Validate relevance (abstract triage)

Before reading the full paper, triage each abstract:

1. Does the abstract mention both the cell line AND a MYC family member
   (MYC, c-MYC, N-MYC, MYCN, L-MYC, MYCL, Myc)?
2. Is the mention substantive — i.e., MYC is part of the actual findings or
   hypothesis, not just listed as a reprogramming factor for iPSCs or used as
   an epitope tag (Myc-tag)?

**Discard** papers that fail triage. For papers that pass, proceed to Step 4.

Common false-positive patterns to filter out:
- "Myc-tagged" / "c-Myc epitope tag" — immunoprecipitation tagging, not oncogene
- "c-MYC, KLF4, OCT4, SOX2" in context of iPSC reprogramming
- Cell line name substring collisions (e.g., "PK1" matching "LLC-PK1")
- Generic reviews that mention the cell line in a table but have no MYC data

### Step 4 — Attempt full-text access

For each paper that passes triage, you MUST attempt to download and read the entire full text if available. The process is:

1. **PubMed Central (PMC)**: If a PMC ID is available, download the full paper using the NCBI efetch utility:
  - `efetch -db pmc -id PMC1234567 -format full` (or use the E-utilities API to fetch the full XML/HTML)
  - If BioC JSON is available, use it for clean sectioned text.
  - If not, download the full HTML or XML and extract the main article body.
  - If only a PDF is available, download the PDF and extract text using a PDF extraction tool (e.g., PyPDF, pdfminer, or equivalent).

2. **bioRxiv/medRxiv preprints**: If the DOI starts with `10.1101/`, download the full text from the preprint server:
  - Download the HTML or PDF from `https://www.biorxiv.org/content/DOI.full` or `https://www.medrxiv.org/content/DOI.full`.
  - If only PDF is available, extract text using a PDF extraction tool.

3. **Publisher open access**: For other open access papers, download the full HTML or PDF from the publisher site (e.g., via DOI link).
  - If only PDF is available, extract text using a PDF extraction tool.

4. **Save the full text** as a plain text file (preferred) or as extracted text from PDF/HTML/XML. Always keep the full text for auditability.

If none of the above work, mark the paper as **not free access** and proceed using only the abstract.

### Step 5 — Deep read and extract


This is the critical step. **You are not doing keyword search.**

**You MUST read the entire full text of the paper whenever it is available.**
This means you must process the downloaded full text (from PMC, bioRxiv, publisher, or PDF extraction) and extract substantive information about how MYC relates to the cell line in this study.

If only the abstract is available (paywalled), then use the abstract, but always prefer the full text.

For each paper, produce:

- **myc_summary** (2-4 sentences): In your own words, explain what this study
  found about MYC in the context of this cell line. Be specific. Examples:
  - "This study showed that c-MYC amplification in COLO-320 cells drives
    extrachromosomal DNA (ecDNA) formation, and that BRD4 binds MYC-containing
    ecDNAs to create phase-separated transcriptional hubs."
  - "The authors used siRNA to knock down c-MYC in HT-29 cells and observed
    reduced glycolysis via the SPAG4/c-MYC/SULT2B1 axis."

- **direct_quote** (1-2 sentences): Copy a verbatim quote from the paper (or
  abstract) that most clearly links MYC to the cell line. Always quote exactly.
  Examples:
  - "c-Myc knockdown in MDA-MB-231 cells significantly reduced
    O-GlcNAcylation-mediated chemoresistance to doxorubicin"
  - "A human small cell lung cancer cell line (H82) demonstrates 40- to 50-fold
    amplification of the c-myc gene"

**Quality standards for quotes:**
- The quote MUST come from text you actually read (abstract or full text).
- The quote MUST mention the specific cell line or a clear synonym.
- If the full text is available, prefer quotes from the Results or Discussion
  sections over the Abstract.
- If only the abstract is available, extract the most informative sentence.
- NEVER fabricate or paraphrase a quote. If you cannot find a verbatim sentence
  linking MYC and the cell line, write "No direct quote available — association
  inferred from abstract context" and explain in the summary.

### Step 6 — Write to results.csv

Append each validated paper as a row to `results.csv`:

| Column             | Description                                                |
|--------------------|------------------------------------------------------------|
| cell_line          | Standardized name from `cell_lines.txt`                    |
| tissue             | Tissue type (breast, colon, lung, pancreas, etc.)          |
| pmid               | PubMed ID (numeric)                                        |
| paper_title        | Full title of the paper                                    |
| is_free_access     | `yes` if full text was readable, `no` if only abstract     |
| paper_url          | `https://pubmed.ncbi.nlm.nih.gov/PMID/`                   |
| myc_summary        | Your 2-4 sentence summary of the MYC finding               |
| direct_quote       | Verbatim quote from the paper/abstract                     |
| search_timestamp   | ISO 8601 timestamp of when the search was performed        |

**CSV hygiene**: Wrap fields containing commas or quotes in double-quotes. Escape
internal double-quotes by doubling them (`""`). Use Python's `csv` module or
equivalent to handle this automatically.

### Step 7 — Report progress and continue

After finishing a cell line, print a brief status:
```
[3/40] MDAMB231 (breast) — 8 papers found, 5 with full text
```

Then move to the next cell line. **Do not stop to ask the human.** Continue until
all cell lines are processed.

## What you CAN do

- Read `cell_lines.txt` — this is your input.
- Write to `results.csv` — this is your output.
- Fetch web pages to read papers (PubMed, PMC, bioRxiv, publisher sites).
- Use NCBI E-utilities APIs for search and metadata.
- Create temporary working files if needed (clean up after).
- Use Python scripts for API calls, HTML parsing, and CSV writing.

## What you CANNOT do

- **Hallucinate paper titles, PMIDs, or quotes.** Every PMID must come from an
  actual PubMed API response. Every quote must come from text you actually
  fetched and read. If you are unsure, say so explicitly.
- **Skip the reading step.** A keyword match in the abstract is not sufficient.
  You must read and understand the context of the MYC mention.
- **Modify `cell_lines.txt`.** It is read-only input.
- **Scrape paywalled content** past what is freely accessible. If a paper is
  behind a paywall, mark it as `is_free_access=no` and work from the abstract
  only.
- **Exceed NCBI rate limits.** Stay under 3 requests/second without an API key.

## Decision criteria

**Keep** a paper if:
- The study uses the specific cell line (not just mentions it in a list).
- MYC (or a family member) is a meaningful part of the study — as a target,
  biomarker, pathway component, or therapeutic axis.
- You can extract a substantive summary and ideally a direct quote.

**Discard** a paper if:
- The cell line is only mentioned in passing (e.g., in a supplementary table).
- "MYC" appears only as an epitope tag or iPSC reprogramming factor.
- The cell line name matched a false positive (e.g., "H460" matching an
  unrelated "H460" reference).
- The paper is a retraction notice or erratum with no scientific content.

## Edge cases

- **Cell line with zero results**: Log a row with pmid=`NA`, paper_title=
  `No MYC-related papers found`, is_free_access=`NA`, and leave summary/quote
  blank. This makes it clear the cell line was searched, not skipped.
- **Retracted papers**: Note `[RETRACTED]` in the paper_title field. Still
  include if the scientific content is informative, but flag it.
- **Preprints**: Mark as `preprint` in the paper_title field if not yet
  peer-reviewed. Still include.
- **Non-English papers**: Include if the abstract is in English. Note
  `[Non-English full text]` in the summary.

## Output example

```csv
cell_line,tissue,pmid,paper_title,is_free_access,paper_url,myc_summary,direct_quote,search_timestamp
COLO320,colon,37503084,"Phase separation of ecDNA aggregates establishes in-trans contact domains boosting selective MYC regulatory interactions",yes,https://pubmed.ncbi.nlm.nih.gov/37503084/,"This study investigated MYC-harboring extrachromosomal DNAs (ecDNAs) in COLO320-DM cells using polymer modeling. They found that BRD4-mediated phase separation of ecDNA aggregates creates in-trans contact domains that selectively boost MYC regulatory interactions, offering a mechanism for MYC overexpression in colorectal cancer.","Here, we investigate, at the single molecule level, MYC-harboring ecDNAs of COLO320-DM colorectal cancer cells by use of a minimal polymer model of the interactions of ecDNA BRD4 binding sites and BRD4 molecules.",2026-04-08T14:30:00Z
NCIH82,lung,3004717,"Comparison of amplified and unamplified c-myc gene structure and expression in human small cell lung carcinoma cell lines",no,https://pubmed.ncbi.nlm.nih.gov/3004717/,"Classic study establishing that the NCI-H82 SCLC cell line has 40-50 fold c-myc amplification and expresses >250-fold more c-myc mRNA than unamplified SCLC lines. This makes H82 one of the canonical c-MYC-amplified SCLC models.","A human small cell lung cancer cell line (H82) demonstrates 40- to 50-fold amplification of the c-myc gene but expresses at least 250-fold more steady-state c-myc messenger RNA than an unamplified small cell lung cancer cell line (H378) with no detectable expression of c-myc.",2026-04-08T14:30:00Z
```

## Never stop

Once the search loop has begun, do NOT pause to ask the human if you should
continue. Do NOT ask "should I keep going?" or "want me to proceed to the next
cell line?". The human may be away from the computer. Process every cell line in
`cell_lines.txt` from top to bottom. The loop runs until every cell line is done
or the human manually interrupts you.

If a cell line search fails (API error, timeout), log the error, skip it, and
move on. You can retry failed cell lines at the end.

## Post-loop summary

When all cell lines have been processed, print a final summary:

```
=== SEARCH COMPLETE ===
Total cell lines searched: 40
Cell lines with MYC papers: 22
Cell lines with no MYC papers: 18
Total papers in results.csv: 158
Papers with full text access: 47
Papers with abstract only: 111
```

Then tell the human: "All cell lines processed. Results written to results.csv."
