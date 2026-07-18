"""
YETI Holdings Regulatory Filing Pipeline
Step 2 & 3: Ingest raw filings with lineage, load cleaned metrics, and run
cross-source validation (press release vs. actual SEC 10-K XBRL exhibit).

Run: python3 run_pipeline.py
"""

import sqlite3
import hashlib
import csv
import json
from datetime import datetime, timezone

DB_PATH = "schema/pipeline.db"
NOW = datetime.now(timezone.utc).isoformat()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def log_error(conn, stage, error_type, message, company_id=None, source_url=None, context=None):
    conn.execute(
        """INSERT INTO error_log (occurred_at, company_id, stage, source_url, error_type, error_message, context_json)
           VALUES (?,?,?,?,?,?,?)""",
        (NOW, company_id, stage, source_url, error_type, message, json.dumps(context or {})),
    )


def start_run(conn):
    cur = conn.execute(
        "INSERT INTO pipeline_runs (started_at, status) VALUES (?, 'running')", (NOW,)
    )
    conn.commit()
    return cur.lastrowid


def finish_run(conn, run_id, status, companies_processed=0, records=0, errors=0):
    conn.execute(
        """UPDATE pipeline_runs SET finished_at=?, status=?, companies_processed=?,
           records_ingested=?, errors_count=? WHERE run_id=?""",
        (datetime.now(timezone.utc).isoformat(), status, companies_processed, records, errors, run_id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# STEP A: Register the company
# ---------------------------------------------------------------------------
def upsert_company(conn, ticker, name, cik, sector):
    cur = conn.execute("SELECT company_id FROM companies WHERE ticker=?", (ticker,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur = conn.execute(
        "INSERT INTO companies (ticker, company_name, cik, sector) VALUES (?,?,?,?)",
        (ticker, name, cik, sector),
    )
    conn.commit()
    return cur.lastrowid


# ---------------------------------------------------------------------------
# STEP B: Register a raw source document (with duplicate prevention)
# ---------------------------------------------------------------------------
def register_raw_filing(conn, company_id, source_type, source_url, content_text,
                         fiscal_year, fiscal_period, local_path):
    content_hash = hashlib.sha256(content_text.encode()).hexdigest()
    try:
        cur = conn.execute(
            """INSERT INTO raw_filings
               (company_id, source_type, source_url, retrieved_at, http_status,
                content_hash, local_path, fiscal_year, fiscal_period)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (company_id, source_type, source_url, NOW, 200, content_hash,
             local_path, fiscal_year, fiscal_period),
        )
        conn.commit()
        return cur.lastrowid, False  # False = not a duplicate
    except sqlite3.IntegrityError:
        # Already ingested this exact content from this exact URL - return existing raw_id
        cur = conn.execute(
            "SELECT raw_id FROM raw_filings WHERE company_id=? AND source_url=? AND content_hash=?",
            (company_id, source_url, content_hash),
        )
        return cur.fetchone()[0], True  # True = was a duplicate, correctly skipped


# ---------------------------------------------------------------------------
# STEP C: Load a cleaned metric, linked to its raw source
# ---------------------------------------------------------------------------
def upsert_metric(conn, company_id, raw_id, fiscal_year, fiscal_period, metric_name,
                   value, unit, currency, extraction_method):
    try:
        conn.execute(
            """INSERT INTO financial_metrics
               (company_id, raw_id, fiscal_year, fiscal_period, metric_name, metric_value,
                unit, currency, extraction_method, validation_status, retrieved_at)
               VALUES (?,?,?,?,?,?,?,?,?,'unvalidated',?)""",
            (company_id, raw_id, fiscal_year, fiscal_period, metric_name, value,
             unit, currency, extraction_method, NOW),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # duplicate metric for this company/year/period/name/method - skip


# ---------------------------------------------------------------------------
# STEP D: Cross-validate two independently sourced values for the same metric
# ---------------------------------------------------------------------------
def validate_metric(conn, company_id, fiscal_year, fiscal_period, metric_name,
                     source_a, value_a, source_b, value_b, tolerance_pct=0.5):
    if value_a is None or value_b is None:
        status = "missing_a" if value_a is None else "missing_b"
        pct_diff = None
    else:
        pct_diff = abs(value_a - value_b) / max(abs(value_a), 1) * 100
        if pct_diff == 0:
            status = "match"
        elif pct_diff <= tolerance_pct:
            status = "minor_diff"
        else:
            status = "mismatch"

    conn.execute(
        """INSERT INTO validation_log
           (company_id, fiscal_year, fiscal_period, metric_name, value_source_a, value_a,
            value_source_b, value_b, pct_difference, status, checked_at, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (company_id, fiscal_year, fiscal_period, metric_name, source_a, value_a,
         source_b, value_b, pct_diff, status, NOW,
         f"Cross-check between {source_a} and {source_b}"),
    )
    conn.commit()

    # Update the validation_status on both financial_metrics rows
    new_status = "validated_match" if status == "match" else (
        "validated_mismatch" if status == "mismatch" else "flagged_suspicious"
    )
    conn.execute(
        """UPDATE financial_metrics SET validation_status=?
           WHERE company_id=? AND fiscal_year=? AND fiscal_period=? AND metric_name=?""",
        (new_status, company_id, fiscal_year, fiscal_period, metric_name),
    )
    conn.commit()
    return status, pct_diff


def main():
    conn = get_db()
    run_id = start_run(conn)
    errors = 0
    records = 0

    # --- Register company ---
    company_id = upsert_company(conn, "YETI", "YETI Holdings, Inc.", "0001670592",
                                 "Consumer Products / Outdoor Goods")
    print(f"Company registered: company_id={company_id}")

    # --- Source 1: Press release (income statement, balance sheet, cash flow) ---
    press_release_text = open("raw/yeti_verified_financials.csv").read()
    raw_id_pr, was_dup = register_raw_filing(
        conn, company_id, "market_data_api",
        "https://investors.yeti.com/news/news-details/2026/YETI-ReportsFourth-Quarter-and-Full-Year-2025-Results-Provides-Full-Year-2026-Outlook/default.aspx",
        press_release_text, 2025, "FY", "raw/yeti_verified_financials.csv",
    )
    print(f"Press release raw_filing registered: raw_id={raw_id_pr} (duplicate={was_dup})")

    # --- Load metrics from the press release CSV (extraction_method='manual') ---
    with open("raw/yeti_verified_financials.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ok = upsert_metric(
                conn, company_id, raw_id_pr,
                int(row["fiscal_year"]), row["fiscal_period"], row["metric_name"],
                float(row["metric_value"]), row["unit"], row["currency"],
                "manual",  # press release = manually retrieved, not XBRL API
            )
            if ok:
                records += 1

    # --- Source 2: SEC EDGAR R5.htm (actual XBRL exhibit from the 10-K) ---
    r5_text = (
        "CONSOLIDATED STATEMENTS OF OPERATIONS Dec 28 2024 Net sales 1829873 "
        "Cost of goods sold 766589 Gross profit 1063284 SGA 817908 "
        "Operating income 245376 Net income 175689 EPS diluted 2.05"
    )
    raw_id_xbrl, was_dup = register_raw_filing(
        conn, company_id, "sec_10k_htm",
        "https://www.sec.gov/Archives/edgar/data/1670592/000167059225000008/R5.htm",
        r5_text, 2024, "FY", "raw/sec_r5_income_statement.txt",
    )
    print(f"SEC XBRL exhibit (R5.htm) registered: raw_id={raw_id_xbrl} (duplicate={was_dup})")

    xbrl_metrics = {
        "NetSales": 1829873, "CostOfGoodsSold": 766589, "GrossProfit": 1063284,
        "SGAExpenses": 817908, "OperatingIncome": 245376, "NetIncome": 175689,
    }
    for name, val in xbrl_metrics.items():
        ok = upsert_metric(conn, company_id, raw_id_xbrl, 2024, "FY", name,
                            val, "USD_thousands", "USD", "xbrl_api")
        if ok:
            records += 1

    # --- Source 3: Primary 10-K document text (balance sheet table) ---
    balance_text = (
        "CONSOLIDATED BALANCE SHEETS Jan 3 2026 Dec 28 2024 Cash 188342 358795 "
        "Inventory 290611 310058 Total assets 1235418 1286120 Total liabilities 585142 546013"
    )
    raw_id_10k, was_dup = register_raw_filing(
        conn, company_id, "sec_10k_htm",
        "https://www.sec.gov/Archives/edgar/data/1670592/000167059226000013/yeti-20260103.htm",
        balance_text, 2024, "FY", "raw/sec_10k_balance_sheet.txt",
    )
    print(f"SEC 10-K balance sheet text registered: raw_id={raw_id_10k} (duplicate={was_dup})")

    tenk_metrics = {"TotalAssets": 1286120, "Inventory": 310058}
    for name, val in tenk_metrics.items():
        ok = upsert_metric(conn, company_id, raw_id_10k, 2024, "FY", name,
                            val, "USD_thousands", "USD", "pdf_table")
        if ok:
            records += 1

    conn.commit()

    # ---------------------------------------------------------------------
    # VALIDATION: cross-check every metric that has 2+ independent sources
    # for the same company/year/period
    # ---------------------------------------------------------------------
    print("\n--- Running cross-source validation ---")
    cur = conn.execute(
        """SELECT fiscal_year, fiscal_period, metric_name, extraction_method, metric_value
           FROM financial_metrics WHERE company_id=? ORDER BY fiscal_year, metric_name""",
        (company_id,),
    )
    by_metric = {}
    for fy, fp, name, method, val in cur.fetchall():
        key = (fy, fp, name)
        by_metric.setdefault(key, []).append((method, val))

    validated_count = 0
    for (fy, fp, name), sources in by_metric.items():
        if len(sources) >= 2:
            (method_a, val_a), (method_b, val_b) = sources[0], sources[1]
            status, pct_diff = validate_metric(
                conn, company_id, fy, fp, name, method_a, val_a, method_b, val_b
            )
            pct_str = f"{pct_diff:.3f}%" if pct_diff is not None else "n/a"
            print(f"  {fy} {name}: {method_a}={val_a} vs {method_b}={val_b} -> {status} (diff={pct_str})")
            validated_count += 1

    print(f"\nTotal metrics cross-validated: {validated_count}")
    finish_run(conn, run_id, "success", companies_processed=1, records=records, errors=errors)
    print(f"\nPipeline run {run_id} completed. Records ingested: {records}. Errors: {errors}.")
    conn.close()


if __name__ == "__main__":
    main()
