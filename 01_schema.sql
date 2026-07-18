-- =====================================================================
-- YETI Holdings — Regulatory Filing Data Pipeline
-- Schema: raw storage, cleaned/validated data, full lineage, error logging
-- Engine: SQLite (portable; ports to Postgres with minor type changes)
-- =====================================================================

-- ---------------------------------------------------------------------
-- DIMENSION: companies
-- One row per company tracked by the pipeline. Supports multi-company
-- scaling without schema changes.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS companies (
    company_id      INTEGER PRIMARY KEY,
    ticker          TEXT UNIQUE NOT NULL,
    company_name    TEXT NOT NULL,
    cik             TEXT UNIQUE NOT NULL,   -- SEC's Central Index Key, e.g. '0001670592'
    sector          TEXT,
    added_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------------
-- RAW LAYER: raw_filings
-- Every document/API response pulled is stored here BEFORE any parsing,
-- with full retrieval metadata. Never overwritten — append-only.
-- This is what lets you reprocess from scratch if parsing logic changes,
-- without re-hitting the source.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_filings (
    raw_id          INTEGER PRIMARY KEY,
    company_id      INTEGER NOT NULL REFERENCES companies(company_id),
    source_type     TEXT NOT NULL CHECK(source_type IN ('sec_api_json','sec_10k_pdf','sec_10k_htm','market_data_api')),
    source_url      TEXT NOT NULL,
    retrieved_at    TIMESTAMP NOT NULL,
    http_status     INTEGER,
    content_hash    TEXT NOT NULL,          -- SHA-256 of raw content; used for change detection
    local_path      TEXT NOT NULL,          -- where the raw file/response is stored on disk
    fiscal_year     INTEGER,
    fiscal_period   TEXT,                   -- 'FY', 'Q1', 'Q2', 'Q3'
    UNIQUE(company_id, source_url, content_hash)  -- prevents duplicate ingestion of identical content
);

-- ---------------------------------------------------------------------
-- CLEAN LAYER: financial_metrics
-- Parsed, normalized, validated values. Every row traces back to exactly
-- one raw_filings row (full lineage), plus explicit unit/currency and a
-- validation status instead of silently trusting the extraction.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS financial_metrics (
    metric_id           INTEGER PRIMARY KEY,
    company_id          INTEGER NOT NULL REFERENCES companies(company_id),
    raw_id              INTEGER NOT NULL REFERENCES raw_filings(raw_id),
    fiscal_year          INTEGER NOT NULL,
    fiscal_period        TEXT NOT NULL,       -- 'FY', 'Q1'..'Q4'
    metric_name          TEXT NOT NULL,       -- e.g. 'Revenues', 'CostOfGoodsSold', 'InventoryNet'
    metric_value          REAL NOT NULL,
    unit                 TEXT NOT NULL,       -- 'USD', 'USD_thousands', 'shares'
    currency              TEXT NOT NULL DEFAULT 'USD',
    extraction_method     TEXT NOT NULL CHECK(extraction_method IN ('xbrl_api','pdf_table','manual')),
    validation_status     TEXT NOT NULL DEFAULT 'unvalidated'
                          CHECK(validation_status IN ('unvalidated','validated_match','validated_mismatch','flagged_suspicious','flagged_stale')),
    retrieved_at          TIMESTAMP NOT NULL,
    is_current            BOOLEAN NOT NULL DEFAULT 1,  -- superseded rows set to 0, never deleted
    UNIQUE(company_id, fiscal_year, fiscal_period, metric_name, extraction_method)
);

-- ---------------------------------------------------------------------
-- VALIDATION LAYER: validation_log
-- Every cross-check performed between two independent extractions of the
-- "same" number (e.g. XBRL API vs. PDF table). This is the audit trail
-- for Q4 — proof that numbers were checked, not assumed correct.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS validation_log (
    validation_id        INTEGER PRIMARY KEY,
    company_id           INTEGER NOT NULL REFERENCES companies(company_id),
    fiscal_year          INTEGER NOT NULL,
    fiscal_period        TEXT NOT NULL,
    metric_name          TEXT NOT NULL,
    value_source_a        TEXT NOT NULL,       -- e.g. 'xbrl_api'
    value_a                REAL,
    value_source_b        TEXT NOT NULL,       -- e.g. 'pdf_table'
    value_b                REAL,
    pct_difference        REAL,
    status                TEXT NOT NULL CHECK(status IN ('match','minor_diff','mismatch','missing_a','missing_b')),
    checked_at            TIMESTAMP NOT NULL,
    notes                 TEXT
);

-- ---------------------------------------------------------------------
-- OPERATIONS LAYER: error_log
-- Every failure during retrieval or parsing. Nothing fails silently.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS error_log (
    error_id             INTEGER PRIMARY KEY,
    occurred_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    company_id           INTEGER REFERENCES companies(company_id),
    stage                TEXT NOT NULL CHECK(stage IN ('retrieval','parsing','validation','export')),
    source_url           TEXT,
    error_type           TEXT NOT NULL,        -- e.g. 'HTTPError', 'ParseError', 'ValueOutOfRange'
    error_message         TEXT NOT NULL,
    context_json          TEXT                  -- freeform JSON blob: request params, partial data, etc.
);

-- ---------------------------------------------------------------------
-- OPERATIONS LAYER: pipeline_runs
-- One row per pipeline execution — supports staleness detection
-- ("when was this last successfully refreshed?").
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id                INTEGER PRIMARY KEY,
    started_at            TIMESTAMP NOT NULL,
    finished_at           TIMESTAMP,
    status                TEXT NOT NULL CHECK(status IN ('running','success','partial_failure','failed')),
    companies_processed    INTEGER DEFAULT 0,
    records_ingested       INTEGER DEFAULT 0,
    errors_count           INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_raw_company ON raw_filings(company_id, retrieved_at);
CREATE INDEX IF NOT EXISTS idx_metrics_lookup ON financial_metrics(company_id, fiscal_year, fiscal_period, metric_name);
CREATE INDEX IF NOT EXISTS idx_validation_lookup ON validation_log(company_id, fiscal_year, metric_name);
