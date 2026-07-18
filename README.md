<p align="center">
  <img src="thumbnails/01_github_social_preview.png" alt="YETI Holdings Data Pipeline" width="100%">
</p>

# YETI Holdings — Regulatory Filing Data Pipeline

A repeatable data engineering pipeline that pulls a real public company's
financial data from **three independent official sources** — an
investor-relations press release, an SEC EDGAR XBRL exhibit, and a
directly-parsed PDF filing — stores every source with full lineage,
cross-validates every number that appears in more than one source, and
flags anomalies instead of guessing.

**Live interactive dashboard:** open `05_Dashboard/01_dashboard.html`
directly in any browser (no server needed) — or **[view it hosted here](#)**
if published via GitHub Pages.

## Result
- **44 financial data points** ingested from 3 independent real sources (SEC EDGAR, YETI investor relations, direct PDF parsing)
- **24 of 24 cross-validated metrics matched at 0.000% difference**
- **1 real PDF-extraction bug found and fixed** (a ligature-encoding issue that silently deleted "fi"/"fl" letter pairs — see `02_PDF_Extraction/`)
- **Zero silent failures** — every gap and every duplicate is logged, not hidden

## Why this project exists
This was built to demonstrate the exact skills required for data
engineering work involving regulatory filings and multi-source
validation: schema design with full data lineage, real PDF/HTML
extraction from SEC EDGAR, cross-source validation logic, and honest
handling of missing or conflicting data. See `06_Proposal_Answers/` for
how each part of this project maps directly to that kind of brief.

---

## Folder structure & how to run each part

### `01_Schema_Design/`
1. `01_schema.sql` — the full database schema (6 tables: companies, raw_filings, financial_metrics, validation_log, error_log, pipeline_runs)
2. `02_design_rationale.md` — why each design decision was made (duplicate prevention, lineage, units/currency, staleness)

**To run:** needs no separate install — see `03_Pipeline_Ingestion/05_pipeline.db` for the already-built database, or rebuild it yourself:
```bash
python3 -c "import sqlite3; db=sqlite3.connect('pipeline.db'); db.executescript(open('01_schema.sql').read()); db.commit()"
```

### `02_PDF_Extraction/`
1. `01_pdf_extract.py` — parses a real PDF earnings release, including a custom fix for a genuine ligature-encoding bug
2. `02_raw_pdf_text_with_ligature_bug.txt` — the actual corrupted text as extracted from the PDF
3. `03_ligature_corrections_log.csv` — every correction made, logged for human review (never applied silently)
4. `04_extracted_metrics.csv` — the final structured financial table extracted from the PDF
5. `05_retrieval_method_note.md` — real decision log on choosing this method over scraping/APIs

**To run:**
```bash
cd 02_PDF_Extraction
python3 01_pdf_extract.py
```

### `03_Pipeline_Ingestion/`
1. `01_run_pipeline.py` — ingests raw filings + loads cleaned metrics + runs cross-validation
2. `02_load_pdf_metrics.py` — loads the PDF-extracted metrics and validates them against the press release
3. `03_source_data_press_release.csv` — verified source data with full citations
4. `04_retrieval_log.json` — every source URL, retrieval timestamp, and publisher
5. `05_pipeline.db` — the finished SQLite database (open with DB Browser for SQLite)

**To run:**
```bash
pip install --upgrade pip
cd 03_Pipeline_Ingestion
python3 01_run_pipeline.py
python3 02_load_pdf_metrics.py
```

### `04_Validation_And_Flagging/`
1. `01_validate_and_flag.py` — staleness detection, suspicious-value sanity checks, and missing-metric detection

**To run:**
```bash
cd 04_Validation_And_Flagging
python3 01_validate_and_flag.py
```

### `05_Dashboard/`
1. `01_dashboard.html` — **fully interactive dashboard, open directly in any browser** — tabs for Overview, Financial Trends, Validation Audit, Data Lineage, and Pipeline Run history
2. `02_dashboard_data.json` — the exported dataset the dashboard reads from

**To run:** just double-click `01_dashboard.html`, or drag it into any browser tab. No install needed.

### `06_Proposal_Answers/`
1. `01_proposal_answers.md` — polished, evidence-backed answers to the 5 standard data-engineering screening questions, each pointing back to the exact file that proves it

---

## Tech stack
Python · SQLite · SQL (joins, constraints, indexes) · Regex-based text/table extraction · Data validation & anomaly detection · HTML/CSS/JavaScript (Chart.js) for the dashboard

## Data sources (all real, all cited)
- SEC EDGAR — CIK 0001670592 (YETI Holdings, Inc.)
- YETI Investor Relations — Q4 & Full Year 2025 earnings release
- Full source URLs and retrieval timestamps: `03_Pipeline_Ingestion/04_retrieval_log.json`
