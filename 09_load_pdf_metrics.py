"""
YETI Holdings Regulatory Filing Pipeline
Step: Load PDF-extracted metrics (FY2025) and cross-validate against the
press-release-sourced values already in financial_metrics.

Run: python3 load_pdf_metrics.py  (run after run_pipeline.py and pdf_extract.py)
"""

import sqlite3
import hashlib
import csv
from datetime import datetime, timezone

DB_PATH = "schema/pipeline.db"
NOW = datetime.now(timezone.utc).isoformat()

METRIC_NAME_MAP = {
    "Net sales": "NetSales", "Cost of goods sold": "CostOfGoodsSold",
    "Gross profit": "GrossProfit", "Operating income": "OperatingIncome",
    "Net income": "NetIncome", "Cash": "Cash", "Inventory": "Inventory",
    "Total assets": "TotalAssets", "Total liabilities": "TotalLiabilities",
}


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    cur = conn.execute("SELECT company_id FROM companies WHERE ticker='YETI'")
    company_id = cur.fetchone()[0]

    # Register the PDF as a raw source (content hash of the actual extracted text)
    pdf_text = open("raw/yeti_pdf_press_release_raw.txt").read()
    content_hash = hashlib.sha256(pdf_text.encode()).hexdigest()
    pdf_url = ("https://s22.q4cdn.com/322452763/files/doc_news/"
               "YETI-ReportsFourth-Quarter-and-Full-Year-2025-Results-"
               "Provides-Full-Year-2026-Outlook-2026.pdf")
    try:
        cur = conn.execute(
            """INSERT INTO raw_filings (company_id, source_type, source_url, retrieved_at,
               http_status, content_hash, local_path, fiscal_year, fiscal_period)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (company_id, "sec_10k_pdf", pdf_url, NOW, 200, content_hash,
             "raw/yeti_pdf_press_release_raw.txt", 2025, "FY"),
        )
        raw_id = cur.lastrowid
        conn.commit()
        print(f"PDF raw_filing registered: raw_id={raw_id}")
    except sqlite3.IntegrityError:
        cur = conn.execute(
            "SELECT raw_id FROM raw_filings WHERE company_id=? AND source_url=? AND content_hash=?",
            (company_id, pdf_url, content_hash),
        )
        raw_id = cur.fetchone()[0]
        print(f"PDF raw_filing already registered (duplicate correctly skipped): raw_id={raw_id}")

    # Load extracted metrics for BOTH years present in the PDF table
    inserted = 0
    with open("raw/pdf_extracted_metrics.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            metric_name = METRIC_NAME_MAP.get(row["metric_name"])
            if not metric_name:
                continue
            for year_key, fy in [("fy2025_value", 2025), ("fy2024_value", 2024)]:
                try:
                    conn.execute(
                        """INSERT INTO financial_metrics
                           (company_id, raw_id, fiscal_year, fiscal_period, metric_name,
                            metric_value, unit, currency, extraction_method,
                            validation_status, retrieved_at)
                           VALUES (?,?,?,?,?,?,?,?,?,'unvalidated',?)""",
                        (company_id, raw_id, fy, "FY", metric_name,
                         float(row[year_key]), "USD_thousands", "USD", "pdf_table", NOW),
                    )
                    inserted += 1
                except sqlite3.IntegrityError:
                    pass  # already loaded (e.g. Total assets/Inventory FY2024 from earlier step)
    conn.commit()
    print(f"PDF-extracted metrics inserted: {inserted}")

    # --- Cross-validate FY2025 metrics: manual (press release) vs pdf_table (this PDF) ---
    print("\n--- Cross-validating FY2025 (previously single-sourced) ---")
    cur = conn.execute(
        """SELECT fiscal_year, metric_name, extraction_method, metric_value
           FROM financial_metrics WHERE company_id=? AND fiscal_year=2025
           ORDER BY metric_name""",
        (company_id,),
    )
    by_metric = {}
    for fy, name, method, val in cur.fetchall():
        by_metric.setdefault(name, {})[method] = val

    for name, sources in by_metric.items():
        if "manual" in sources and "pdf_table" in sources:
            val_a, val_b = sources["manual"], sources["pdf_table"]
            pct_diff = abs(val_a - val_b) / max(abs(val_a), 1) * 100
            status = "match" if pct_diff == 0 else ("minor_diff" if pct_diff <= 0.5 else "mismatch")
            conn.execute(
                """INSERT INTO validation_log
                   (company_id, fiscal_year, fiscal_period, metric_name, value_source_a, value_a,
                    value_source_b, value_b, pct_difference, status, checked_at, notes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (company_id, 2025, "FY", name, "manual", val_a, "pdf_table", val_b,
                 pct_diff, status, NOW, "Press release vs. independently-parsed PDF"),
            )
            new_status = "validated_match" if status == "match" else "flagged_suspicious"
            conn.execute(
                """UPDATE financial_metrics SET validation_status=?
                   WHERE company_id=? AND fiscal_year=2025 AND metric_name=?""",
                (new_status, company_id, name),
            )
            print(f"  {name}: manual={val_a:,.0f} vs pdf_table={val_b:,.0f} -> {status} (diff={pct_diff:.3f}%)")

    conn.commit()
    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
