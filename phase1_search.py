#!/usr/bin/env python3
"""
Phase 1: Search PubMed, triage abstracts, download full texts, organise on disk.
"""

import csv
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
WORKING_DIR = Path(__file__).parent
CELL_LINES_CSV = WORKING_DIR / "cell_lines.csv"
RESULTS_CSV = WORKING_DIR / "results.csv"
PAPERS_DIR = WORKING_DIR / "papers"

NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
RATE_LIMIT_DELAY = 0.4          # seconds between NCBI API calls
REQUEST_TIMEOUT = 30            # seconds
MAX_PAPERS_PER_CELL_LINE = 20

MYC_TERMS = (
    'MYC OR c-MYC OR "MYC amplification" OR "MYC-driven" OR '
    '"N-MYC" OR MYCN OR "L-MYC" OR MYCL'
)

RESULTS_FIELDNAMES = [
    "cell_line", "tissue", "pmid", "pmcid",
    "paper_title", "is_free_access", "paper_url", "search_timestamp",
]

# MYC family patterns for triage
MYC_PATTERN = re.compile(
    r'\b(c-?MYC|MYCN|N-?MYC|MYCL|L-?MYC|Myc)\b', re.IGNORECASE
)

# iPSC / epitope-tag false-positive patterns
FALSE_POSITIVE_PATTERN = re.compile(
    r'(Myc.?tag|c-Myc epitope tag|KLF4.*OCT4|OCT4.*KLF4|'
    r'reprogramming factor|induced pluripotent)',
    re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Cell line name variant generator
# ---------------------------------------------------------------------------
def cell_line_variants(name: str) -> list[str]:
    """Generate common search variants for a cell line name."""
    variants = {name}

    # NCI-H* variants: NCIH460 -> NCI-H460, H460
    m = re.match(r'^NCI[-_]?H(\d+)([A-Z]*)$', name, re.IGNORECASE)
    if not m:
        m = re.match(r'^NCIH(\d+)([A-Z]*)$', name, re.IGNORECASE)
    if m:
        num, suffix = m.group(1), m.group(2)
        variants.update([
            f"NCI-H{num}{suffix}",
            f"H{num}{suffix}",
            f"NCIH{num}{suffix}",
        ])

    # MDA-MB-* variants: MDAMB231 -> MDA-MB-231
    m = re.match(r'^MDA[-_]?MB[-_]?(\d+)([A-Z]*)$', name, re.IGNORECASE)
    if not m:
        m = re.match(r'^MDAMB(\d+)([A-Z]*)$', name, re.IGNORECASE)
    if m:
        num, suffix = m.group(1), m.group(2)
        variants.update([
            f"MDA-MB-{num}{suffix}",
            f"MDAMB{num}{suffix}",
        ])

    # HCC* variants: no dashes usually, keep as-is
    # RERF-LC-* variants: RERFLCAI -> RERF-LC-AI
    m = re.match(r'^RERFLC(.+)$', name, re.IGNORECASE)
    if m:
        variants.update([
            f"RERF-LC-{m.group(1).upper()}",
            f"RERFLC{m.group(1).upper()}",
        ])

    # HOP* -> no special variant
    # MSTO-211H -> MSTO211H
    m = re.match(r'^MSTO[-_]?(\d+)([A-Z]*)$', name, re.IGNORECASE)
    if not m:
        m = re.match(r'^MSTO(\d+)([A-Z]*)$', name, re.IGNORECASE)
    if m:
        num, suffix = m.group(1), m.group(2)
        variants.update([
            f"MSTO-{num}{suffix}",
            f"MSTO{num}{suffix}",
        ])

    # SW* variants: no special transforms needed beyond keeping original
    # CORL* variants: CORL23 -> COR-L23
    m = re.match(r'^CORL(\d+.*)$', name, re.IGNORECASE)
    if m:
        variants.update([
            f"COR-L{m.group(1).upper()}",
            f"CORL{m.group(1).upper()}",
        ])

    # DMS* variants: keep as-is
    # LCLC* variants: LCLC97TM1 -> LCLC-97TM1
    m = re.match(r'^LCLC(\d+.*)$', name, re.IGNORECASE)
    if m:
        variants.update([
            f"LCLC-{m.group(1).upper()}",
        ])

    # Generic: insert dash before digit sequences for camelCase-like names
    # e.g. SCLC22H -> SCLC-22H
    m = re.match(r'^([A-Z]+)(\d+[A-Z]*)$', name)
    if m:
        variants.add(f"{m.group(1)}-{m.group(2)}")

    return list(variants)


def build_query(name: str) -> str:
    variants = cell_line_variants(name)
    variant_str = " OR ".join(f'"{v}"' for v in variants)
    return f'({variant_str}) AND ({MYC_TERMS})'


# ---------------------------------------------------------------------------
# NCBI API helpers
# ---------------------------------------------------------------------------
session = requests.Session()
session.headers.update({"User-Agent": "autolitsearch/1.0 (research; contact via GitHub)"})

_last_ncbi_call = 0.0


def ncbi_get(url: str, params: dict, max_retries: int = 6) -> requests.Response:
    """GET with enforced rate limiting and exponential backoff on 429."""
    global _last_ncbi_call
    delay = 1.0
    for attempt in range(max_retries):
        elapsed = time.time() - _last_ncbi_call
        if elapsed < RATE_LIMIT_DELAY:
            time.sleep(RATE_LIMIT_DELAY - elapsed)
        resp = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        _last_ncbi_call = time.time()
        if resp.status_code == 429:
            wait = delay * (2 ** attempt)
            print(f"  [429] Rate limited — waiting {wait:.1f}s before retry {attempt+1}/{max_retries}")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp
    # Final attempt after all retries
    resp.raise_for_status()
    return resp


def esearch(query: str) -> list[str]:
    resp = ncbi_get(
        f"{NCBI_BASE}/esearch.fcgi",
        {"db": "pubmed", "term": query, "retmode": "json",
         "retmax": MAX_PAPERS_PER_CELL_LINE, "sort": "relevance"},
    )
    data = resp.json()
    return data.get("esearchresult", {}).get("idlist", [])


def efetch_pubmed(pmids: list[str]) -> ET.Element:
    resp = ncbi_get(
        f"{NCBI_BASE}/efetch.fcgi",
        {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"},
    )
    return ET.fromstring(resp.content)


def parse_articles(root: ET.Element) -> list[dict]:
    articles = []
    for article_el in root.findall(".//PubmedArticle"):
        pmid_el = article_el.find(".//PMID")
        pmid = pmid_el.text.strip() if pmid_el is not None else ""

        title_el = article_el.find(".//ArticleTitle")
        title = "".join(title_el.itertext()).strip() if title_el is not None else ""

        # Abstract: may have multiple <AbstractText> with Label attr
        abstract_parts = []
        for ab in article_el.findall(".//AbstractText"):
            label = ab.get("Label", "")
            text = "".join(ab.itertext()).strip()
            if label:
                abstract_parts.append(f"{label}: {text}")
            else:
                abstract_parts.append(text)
        abstract = " ".join(abstract_parts)

        # DOI
        doi = ""
        for loc in article_el.findall(".//ELocationID"):
            if loc.get("EIdType") == "doi":
                doi = loc.text.strip() if loc.text else ""
                break

        # PMCID
        pmcid = ""
        for aid in article_el.findall(".//ArticleId"):
            if aid.get("IdType") == "pmc":
                pmcid = aid.text.strip() if aid.text else ""
                break

        articles.append({
            "pmid": pmid,
            "pmcid": pmcid,
            "title": title,
            "abstract": abstract,
            "doi": doi,
        })
    return articles


# ---------------------------------------------------------------------------
# Abstract triage
# ---------------------------------------------------------------------------
def passes_triage(cell_line_name: str, abstract: str, title: str) -> bool:
    text = f"{title} {abstract}"
    if not MYC_PATTERN.search(text):
        return False
    if FALSE_POSITIVE_PATTERN.search(abstract):
        return False
    # Check cell line variants appear in the text
    variants = cell_line_variants(cell_line_name)
    found_cell_line = any(
        re.search(r'\b' + re.escape(v) + r'\b', text, re.IGNORECASE)
        for v in variants
    )
    if not found_cell_line:
        return False
    return True


# ---------------------------------------------------------------------------
# Full-text download
# ---------------------------------------------------------------------------
def fetch_pmc_fulltext(pmcid: str) -> str | None:
    """Try BioC JSON first, then efetch XML."""
    # BioC JSON
    try:
        bioc_url = f"https://www.ncbi.nlm.nih.gov/research/bioxcel/fetch/?pmcid={pmcid}"
        resp = session.get(bioc_url, timeout=REQUEST_TIMEOUT)
        time.sleep(RATE_LIMIT_DELAY)
        if resp.status_code == 200:
            data = resp.json()
            texts = []
            for doc in data.get("documents", []):
                for passage in doc.get("passages", []):
                    t = passage.get("text", "").strip()
                    if t:
                        texts.append(t)
            if texts:
                return "\n\n".join(texts)
    except Exception:
        pass

    # efetch XML
    try:
        resp = ncbi_get(
            f"{NCBI_BASE}/efetch.fcgi",
            {"db": "pmc", "id": pmcid, "rettype": "full", "retmode": "xml"},
        )
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.content, "lxml-xml")
            body = soup.find("body")
            if body:
                return body.get_text(separator="\n").strip()
            # fallback: entire article text
            article = soup.find("article")
            if article:
                return article.get_text(separator="\n").strip()
    except Exception:
        pass

    return None


def fetch_biorxiv_fulltext(doi: str) -> str | None:
    for base in ["https://www.biorxiv.org/content", "https://www.medrxiv.org/content"]:
        try:
            url = f"{base}/{doi}.full"
            resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            time.sleep(RATE_LIMIT_DELAY)
            if resp.status_code == 200 and "text/html" in resp.headers.get("Content-Type", ""):
                soup = BeautifulSoup(resp.text, "lxml")
                article = soup.find("div", class_=re.compile(r'article|fulltext|content', re.I))
                if article:
                    return article.get_text(separator="\n").strip()
        except Exception:
            pass
    return None


def fetch_publisher_fulltext(doi: str) -> str | None:
    try:
        url = f"https://doi.org/{doi}"
        resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        time.sleep(RATE_LIMIT_DELAY)
        if resp.status_code == 200 and "text/html" in resp.headers.get("Content-Type", ""):
            soup = BeautifulSoup(resp.text, "lxml")
            # Try common open-access article body selectors
            for selector in [
                "article", "[class*='article-body']", "[class*='fulltext']",
                "[class*='article__body']", "main", "[role='main']",
            ]:
                el = soup.select_one(selector)
                if el:
                    text = el.get_text(separator="\n").strip()
                    if len(text) > 500:
                        return text
    except Exception:
        pass
    return None


def attempt_fulltext(pmcid: str, doi: str) -> tuple[str | None, bool]:
    """Returns (text, is_free_access)."""
    # 1. PMC
    if pmcid:
        text = fetch_pmc_fulltext(pmcid)
        if text and len(text) > 200:
            return text, True

    # 2. bioRxiv / medRxiv
    if doi and doi.startswith("10.1101/"):
        text = fetch_biorxiv_fulltext(doi)
        if text and len(text) > 200:
            return text, True

    # 3. Publisher open access
    if doi:
        text = fetch_publisher_fulltext(doi)
        if text and len(text) > 200:
            return text, True

    return None, False


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------
def save_paper_files(
    paper_dir: Path,
    abstract: str,
    fulltext: str | None,
    metadata: dict,
):
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "abstract.txt").write_text(abstract, encoding="utf-8")
    if fulltext:
        (paper_dir / "fulltext.txt").write_text(fulltext, encoding="utf-8")
    (paper_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_results_csv() -> set[str]:
    """Return set of cell_line names that were successfully processed.

    A cell line is considered done only if it has at least one row where pmid
    is not 'ERROR' (i.e. the API call actually succeeded, even if no papers
    passed triage — 'NA' rows from zero-results are fine).
    """
    done: set[str] = set()
    errored: set[str] = set()
    if not RESULTS_CSV.exists():
        return done
    with open(RESULTS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cl = row.get("cell_line", "").strip()
            pmid = row.get("pmid", "").strip()
            if pmid == "ERROR":
                errored.add(cl)
            else:
                done.add(cl)
    # Cell lines that have only ERROR rows need to be re-searched
    retry = errored - done
    if retry:
        print(f"  [RESUME] {len(retry)} cell line(s) had only errors last run — will retry: {', '.join(sorted(retry)[:10])}{'...' if len(retry) > 10 else ''}")
    return done


def init_results_csv():
    if not RESULTS_CSV.exists():
        with open(RESULTS_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=RESULTS_FIELDNAMES)
            writer.writeheader()


def append_result(row: dict):
    with open(RESULTS_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RESULTS_FIELDNAMES)
        writer.writerow(row)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def read_cell_lines() -> list[dict]:
    cell_lines = []
    with open(CELL_LINES_CSV, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("cell_line", "").strip()
            tissue = row.get("tissue", "").strip()
            if name and not name.startswith("#"):
                cell_lines.append({"name": name, "tissue": tissue})
    return cell_lines


def process_cell_line(cl: dict, index: int, total: int) -> tuple[int, int, int]:
    """Returns (found, passed_triage, with_fulltext)."""
    name = cl["name"]
    tissue = cl["tissue"]
    query = build_query(name)

    # Step 1: Search
    try:
        pmids = esearch(query)
    except Exception as e:
        print(f"  [ERROR] esearch failed for {name}: {e}")
        append_result({
            "cell_line": name, "tissue": tissue, "pmid": "ERROR",
            "pmcid": "", "paper_title": f"Search error: {e}",
            "is_free_access": "NA", "paper_url": "",
            "search_timestamp": datetime.now(timezone.utc).isoformat(),
        })
        return 0, 0, 0

    if not pmids:
        append_result({
            "cell_line": name, "tissue": tissue, "pmid": "NA",
            "pmcid": "", "paper_title": "No MYC-related papers found",
            "is_free_access": "NA", "paper_url": "",
            "search_timestamp": datetime.now(timezone.utc).isoformat(),
        })
        return 0, 0, 0

    found = len(pmids)

    # Step 2: Fetch metadata
    try:
        root = efetch_pubmed(pmids)
        articles = parse_articles(root)
    except Exception as e:
        print(f"  [ERROR] efetch failed for {name}: {e}")
        return found, 0, 0

    passed = 0
    with_ft = 0

    for art in articles:
        pmid = art["pmid"]
        title = art["title"]
        abstract = art["abstract"]
        doi = art["doi"]
        pmcid = art["pmcid"]

        # Step 3: Triage
        if not passes_triage(name, abstract, title):
            continue

        passed += 1

        # Step 4: Attempt full-text download
        fulltext, is_free = attempt_fulltext(pmcid, doi)
        if is_free:
            with_ft += 1

        # Step 5: Save files
        paper_dir = PAPERS_DIR / name / pmid
        metadata = {
            "cell_line": name,
            "tissue": tissue,
            "pmid": pmid,
            "pmcid": pmcid,
            "paper_title": title,
            "doi": doi,
            "is_free_access": is_free,
            "paper_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        }
        save_paper_files(paper_dir, abstract, fulltext, metadata)

        # Step 6: Append to results.csv
        append_result({
            "cell_line": name,
            "tissue": tissue,
            "pmid": pmid,
            "pmcid": pmcid,
            "paper_title": title,
            "is_free_access": "yes" if is_free else "no",
            "paper_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "search_timestamp": datetime.now(timezone.utc).isoformat(),
        })

    if passed == 0:
        append_result({
            "cell_line": name, "tissue": tissue, "pmid": "NA",
            "pmcid": "", "paper_title": "No papers passed triage",
            "is_free_access": "NA", "paper_url": "",
            "search_timestamp": datetime.now(timezone.utc).isoformat(),
        })

    return found, passed, with_ft


def main():
    print("=== Phase 1: Search, Filter, and Collect ===\n")

    PAPERS_DIR.mkdir(exist_ok=True)
    init_results_csv()

    cell_lines = read_cell_lines()
    already_done = load_results_csv()

    queued = [cl for cl in cell_lines if cl["name"] not in already_done]
    print(f"Total cell lines in file : {len(cell_lines)}")
    print(f"Already processed        : {len(already_done)}")
    print(f"Queued for this run      : {len(queued)}")
    print()

    total = len(queued)
    total_found = 0
    total_passed = 0
    total_ft = 0
    lines_with_papers = 0
    lines_without_papers = 0

    for i, cl in enumerate(queued, 1):
        name = cl["name"]
        tissue = cl["tissue"]
        print(f"[{i}/{total}] {name} ({tissue}) — searching...", flush=True)

        found, passed, with_ft = process_cell_line(cl, i, total)

        total_found += found
        total_passed += passed
        total_ft += with_ft

        if passed > 0:
            lines_with_papers += 1
        else:
            lines_without_papers += 1

        print(
            f"[{i}/{total}] {name} ({tissue}) — "
            f"{found} found, {passed} passed triage, {with_ft} with full text"
        )

    print()
    print("=== PHASE 1 COMPLETE ===")
    print(f"Total cell lines searched : {total}")
    print(f"Cell lines with MYC papers: {lines_with_papers}")
    print(f"Cell lines with no results: {lines_without_papers}")
    print(f"Total papers in results.csv: {total_passed}")
    print(f"Papers with full text      : {total_ft}")
    print(f"Papers with abstract only  : {total_passed - total_ft}")
    print("papers/ folder ready for Phase 2.")


if __name__ == "__main__":
    main()
