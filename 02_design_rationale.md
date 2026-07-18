# Pipeline Design Rationale
**Project: YETI Holdings (NYSE: YETI) Regulatory Filing Data Pipeline**

This document explains the design decisions behind `schema.sql`, framed
around the exact requirements a repeatable data pipeline needs: raw
storage, cleaned data, source lineage, retrieval timestamps, units/
currency, duplicate prevention, and staleness detection.

## 1. Raw layer is append-only and never overwritten
`raw_filings` stores every API response and PDF pulled, with a
`content_hash` (SHA-256) and `local_path` pointing to the actual saved
file. Nothing is parsed in place — parsing always reads from this table.
**Why:** if a parsing bug is found six months from now, you reprocess from
the stored raw files instead of re-hitting SEC's servers, and you can
prove exactly what data existed at the time a number was extracted.

## 2. Duplicate prevention
`UNIQUE(company_id, source_url, content_hash)` on `raw_filings` means the
same document, if pulled twice, is only stored once — but if a filing is
*amended* (new content, same URL), the hash differs and it correctly
stores as a new version rather than either duplicating or silently
overwriting.

## 3. Lineage: every clean value traces to one raw record
`financial_metrics.raw_id` is a foreign key back to `raw_filings`. Every
number in the clean layer can answer "which exact document, retrieved
when, did this come from?" — not just "what's the current value."

## 4. Units and currency are explicit, never assumed
`financial_metrics.unit` and `.currency` are required columns, not
metadata living in a README somewhere. SEC XBRL data is sometimes reported
in thousands, sometimes in raw dollars, depending on the filer — treating
this as an explicit column instead of an assumption is what prevents a
1000x error from a unit mismatch.

## 5. Staleness detection
`pipeline_runs` logs every execution with a timestamp. A "data freshness"
check is simply: `MAX(retrieved_at)` per company vs. today's date, flagged
if older than the expected filing cadence (e.g. 100 days for a quarterly
filer). No metric is presented without knowing how old it is.

## 6. Validation is a first-class citizen, not an afterthought
`validation_log` records every cross-check between two independently
extracted values for the same metric (e.g. SEC's XBRL API vs. a
hand-parsed PDF table). Each row has an explicit `status`
(`match`/`minor_diff`/`mismatch`/`missing`), so validation results are
queryable data, not just a pass/fail printed to a console and forgotten.

## 7. Errors are logged, not swallowed
`error_log` captures every retrieval or parsing failure with a `stage`,
`error_type`, and freeform `context_json` for debugging. A pipeline that
silently skips a broken record is worse than one that fails loudly and
logs why.

## 8. Multi-company scaling built in from day one
Even though this demo tracks one company (YETI), `companies` is a proper
dimension table with a `company_id` used everywhere else. Adding a second
or hundredth company requires zero schema changes — just new rows.
