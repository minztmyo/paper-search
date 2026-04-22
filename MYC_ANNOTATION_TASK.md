# MYC Annotation Task for Ollama

## Overview

You are a scientific reviewer analyzing cancer biology literature. We've already downloaded the full texts of papers and have results saved in `results.csv`. Your task is to use local Ollama to read each paper and extract structured, evidence-based annotations about MYC (c-Myc) in specific cell lines.

**Goal**: Determine if MYC overexpression/dependency/amplification are mentioned, and whether functional experiments were performed on each cell line.

**Output**: New columns appended to `results.csv` → saved as `results2.csv`

---

## Scope

### Include
- **MYC** (c-Myc)

### Exclude
- MYCN
- MYCL
- External knowledge or general MYC biology
- Information NOT explicitly stated in the paper

---

## Strict Definitions

### **"MYC amplified"**
Explicit statement of:
- Genomic amplification
- Copy number gain
- Gene amplification of MYC
- Examples: "40-50 fold amplification", "copy number gain", "amplified MYC"

### **"MYC overexpressed"**
Explicit statement of:
- Increased MYC mRNA levels in the cell line
- Increased MYC protein levels in the cell line
- Examples: "high MYC expression", "elevated c-Myc protein", "upregulated MYC mRNA"

### **"MYC dependent"**
**Requires functional experiment** showing:
- Reduced cell viability OR reduced proliferation
- Upon MYC knockdown, CRISPR knockout, or inhibition
- Must show direct causal link (perturbation → phenotype)

**NOT sufficient**:
- Correlation or association alone
- Observational statements
- "MYC is important for growth" without perturbation data

### **"Experiment done"**
Any perturbation or assay performed on the cell line:
- Knockdown (siRNA, shRNA, CRISPR)
- Overexpression (transfection, ectopic expression)
- Drug treatment
- Reporter assays
- Functional assays (viability, proliferation, migration, etc.)

### **"MYC overexpression experiment"**
MYC is artificially increased:
- Transfection with MYC expression vector
- Ectopic MYC expression
- CRISPR activation of MYC
- Examples: "MYC transfection", "ectopic MYC expression"

### **"MYC knockdown"**
MYC is reduced:
- siRNA targeting MYC
- shRNA targeting MYC
- CRISPR knockout of MYC
- Examples: "MYC siRNA", "MYC knockdown", "CRISPR MYC"

### **"MYC viability data"**
Viability or proliferation measured after MYC perturbation:
- Cell counts after knockdown
- MTT/XTT assays after MYC perturbation
- Apoptosis assays after MYC inhibition
- Colony formation after MYC knockdown
- Must show numerical result or clear phenotype

---

## Task

For **EACH cell line** mentioned in the paper:

1. Determine the definitions (above) for **ONLY that cell line**
2. Extract the following fields **ONLY if explicitly supported by text**
3. Provide verbatim quote as evidence (if applicable)
4. Assign confidence score (0-100)

---

## Output Format

### Column Names (Append to results.csv)

```
myc_amplified_mentioned,
myc_overexpressed_mentioned,
myc_dependent_mentioned,
experiment_done,
myc_overexpression_exp,
myc_knockdown,
myc_viability_data,
evidence,
confidence_score
```

### Value Rules

| Column | Values | Notes |
|--------|--------|-------|
| `myc_amplified_mentioned` | YES / NO | Explicit mention of MYC amplification in cell line |
| `myc_overexpressed_mentioned` | YES / NO | Explicit mention of elevated MYC mRNA/protein in cell line |
| `myc_dependent_mentioned` | YES / NO | Evidence from functional perturbation showing reduced viability/growth |
| `experiment_done` | YES / NO / NA | Any functional experiment on this cell line |
| `myc_overexpression_exp` | YES / NO / NA | MYC artificially increased in this cell line |
| `myc_knockdown` | YES / NO / NA | MYC reduced in this cell line (siRNA/shRNA/CRISPR) |
| `myc_viability_data` | YES / NO / NA | Viability/proliferation measured after MYC perturbation |
| `evidence` | String (≤50 words) | Verbatim quote supporting strongest claim; or "NA" |
| `confidence_score` | 0-100 | How confident in the annotations (0=uncertain, 100=definitive) |

### Strict Rules

- Use **YES** only if **explicitly supported** by text
- Otherwise use **NO**
- Use **NA** only if not applicable or not mentioned
- **Do NOT infer** beyond what is stated
- **Do NOT classify** based on general MYC biology
- **Cell-line-specific evidence ONLY**

---

## Evidence Field

### Guidelines

- Provide a **short verbatim quote** (≤25 words) from the paper
- Quote must directly support the strongest annotation claim
- If multiple fields are YES, choose the most relevant evidence
- If no text explicitly supports any annotation → `NA`
- Always include quotes exactly as written in paper

### Examples

✅ Good:
- "MYC knockdown in MDA-MB-231 cells reduced cell viability by 50%"
- "40-fold amplification of MYC in NCI-H82 cells"
- "High MYC protein expression in SCLC cell line H146"

❌ Bad:
- "MYC is important for cancer cell growth" (too general, no cell line context)
- "MYC pathway is activated" (not cell-line specific, no perturbation)
- "Correlation between MYC and proliferation" (correlation ≠ dependence)

---

## Confidence Score

| Score | Interpretation |
|-------|-----------------|
| 90-100 | Definitive evidence; clear, explicit statements |
| 70-89 | Strong evidence; minor ambiguity |
| 50-69 | Moderate evidence; some inference needed (avoid) |
| 0-49 | Uncertain; do NOT use |

---

## Examples

### Example 1: MDA-MB-231 (Breast Cancer)

**Paper statement**: "c-Myc knockdown in MDA-MB-231 cells resulted in 60% reduction in cell proliferation and increased apoptosis."

**Annotations**:
```
myc_amplified_mentioned: NO
myc_overexpressed_mentioned: NO
myc_dependent_mentioned: YES
experiment_done: YES
myc_overexpression_exp: NO
myc_knockdown: YES
myc_viability_data: YES
evidence: "c-Myc knockdown in MDA-MB-231 resulted in 60% reduction in proliferation"
confidence_score: 95
```

### Example 2: NCI-H82 (Lung Cancer)

**Paper statement**: "The NCI-H82 SCLC cell line harbors 40-50 fold amplification of c-MYC gene and expresses high levels of MYC protein."

**Annotations**:
```
myc_amplified_mentioned: YES
myc_overexpressed_mentioned: YES
myc_dependent_mentioned: NO
experiment_done: NO
myc_overexpression_exp: NA
myc_knockdown: NA
myc_viability_data: NA
evidence: "40-50 fold amplification of c-MYC and high MYC protein"
confidence_score: 95
```

### Example 3: SW480 (No Experiments)

**Paper statement**: "SW480 cells express moderate MYC levels. MYC is known to drive proliferation."

**Annotations**:
```
myc_amplified_mentioned: NO
myc_overexpressed_mentioned: NO
myc_dependent_mentioned: NO
experiment_done: NO
myc_overexpression_exp: NA
myc_knockdown: NA
myc_viability_data: NA
evidence: NA
confidence_score: 50
```

---

## Strictness Guidelines

### ❌ Do NOT
- Infer dependency without perturbation data
- Use external knowledge about MYC biology
- Accept correlation as evidence of dependence
- Classify based on general statements ("MYC drives growth")
- Include data about MYCN, MYCL, or other MYC family members

### ✅ Do
- Require explicit text for every claim
- Use cell-line-specific evidence only
- Distinguish between observation (expression) and function (dependency)
- Require functional experiments for "dependent" classification
- Quote verbatim from the paper

---

## Workflow

1. **Read the full paper text** (provided by pipeline)
2. **Identify all cell lines** mentioned
3. **For each cell line**, extract relevant MYC information using definitions above
4. **Fill annotation columns** with YES/NO/NA values
5. **Provide verbatim evidence** quote
6. **Assign confidence score** (0-100)
7. **Output row** as CSV-compatible string

---

## CSV Output Format (Exact)

```csv
cell_line,tissue,pmid,paper_title,is_free_access,paper_url,myc_summary,direct_quote,search_timestamp,myc_amplified_mentioned,myc_overexpressed_mentioned,myc_dependent_mentioned,experiment_done,myc_overexpression_exp,myc_knockdown,myc_viability_data,evidence,confidence_score
MDA-MB-231,breast,33275307,"Gold-Based Pharmacophore...",yes,https://pubmed.ncbi.nlm.nih.gov/33275307/,"Study about MYC inhibition...","gold inhibitor affects MYC...",2026-04-20T12:00:00Z,NO,NO,YES,YES,NO,YES,YES,"Compound 1 inhibits MYC activity in MYC-dependent manner",92
```

**Important**: 
- No commas within field values (use semicolons if needed)
- Quote marks only around fields containing commas
- Confidence_score as integer (0-100)

---

## Goals of This Annotation

This structured annotation enables:
- **Systematic analysis** of which cell lines have MYC amplification/overexpression
- **Functional evidence** identifying MYC-dependent cell lines
- **Experimental coverage** showing which lines have been functionally tested
- **High-precision filtering** for downstream computational analysis
- **Reproducible, auditable** annotations tied to verbatim evidence

---

## Contact / Questions

If ambiguity arises:
- Refer back to **STRICT DEFINITIONS**
- Err on the side of **NO** (conservative)
- Mark with low confidence if uncertain
- Do NOT guess or infer
