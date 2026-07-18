"""
YETI Holdings Regulatory Filing Pipeline
Step: Staleness detection + anomaly flagging (answers Q4 directly)

Demonstrates the pipeline's ability to flag - not silently accept -
missing, conflicting, outdated, or suspicious values.

Run: python3 validate_and_flag.py
"""

import sqlite3
from datetime import datetime, timezone

DB_PATH = "schema/pipeline.db"
STALE_THRESHOLD_DAYS = 100  # YETI files quarterly; >100 days since last refresh = stale


def check_staleness(conn):
    """Flags any company whose most recent successful data pull is older
    than the expected filing cadence."""
    print("=== Staleness check ===")
    cur = conn.execute(
        """SELECT c.ticker, MAX(r.retrieved_at) as last_pull
           FROM companies c LEFT JOIN raw_filings r ON r.company_id = c.company_id
           GROUP BY c.company_id"""
    )
    for ticker, last_pull in cur.fetchall():
        if last_pull is None:
            print(f"  {ticker}: NO DATA EVER RETRIEVED - flagged for immediate ingestion")
            continue
        last_dt = datetime.fromisoformat(last_pull)
        age_days = (datetime.now(timezone.utc) - last_dt).days
        status = "STALE - needs refresh" if age_days > STALE_THRESHOLD_DAYS else "fresh"
        print(f"  {ticker}: last retrieved {age_days} days ago -> {status}")


def check_suspicious_values(conn):
    """
    Range/sanity checks on financial_metrics - the pipeline's answer to
    'flag suspicious values rather than guessing.' Examples: negative
    revenue, gross profit exceeding net sales (impossible), inventory
    larger than total assets (impossible), a YoY change so extreme it's
    more likely a data error than a real business event.
    """
    print("\n=== Suspicious value checks ===")
    flagged = 0

    # Check 1: Gross profit should never exceed net sales
    cur = conn.execute(
        """SELECT m1.company_id, m1.fiscal_year, m1.metric_value as gross_profit,
                  m2.metric_value as net_sales
           FROM financial_metrics m1
           JOIN financial_metrics m2 ON m1.company_id=m2.company_id
                AND m1.fiscal_year=m2.fiscal_year AND m1.fiscal_period=m2.fiscal_period
           WHERE m1.metric_name='GrossProfit' AND m2.metric_name='NetSales'
           GROUP BY m1.fiscal_year"""
    )
    for company_id, fy, gp, ns in cur.fetchall():
        if gp > ns:
            print(f"  FLAGGED: FY{fy} GrossProfit (${gp:,.0f}) exceeds NetSales (${ns:,.0f}) - impossible, needs review")
            flagged += 1
        else:
            margin = gp / ns * 100
            print(f"  OK: FY{fy} gross margin = {margin:.1f}% (within plausible 0-100% range)")

    # Check 2: Inventory should never exceed total assets
    cur = conn.execute(
        """SELECT m1.fiscal_year, m1.metric_value as inventory, m2.metric_value as total_assets
           FROM financial_metrics m1
           JOIN financial_metrics m2 ON m1.company_id=m2.company_id
                AND m1.fiscal_year=m2.fiscal_year AND m1.fiscal_period=m2.fiscal_period
           WHERE m1.metric_name='Inventory' AND m2.metric_name='TotalAssets'
           GROUP BY m1.fiscal_year"""
    )
    for fy, inv, ta in cur.fetchall():
        if inv > ta:
            print(f"  FLAGGED: FY{fy} Inventory (${inv:,.0f}) exceeds TotalAssets (${ta:,.0f}) - impossible")
            flagged += 1
        else:
            pct = inv / ta * 100
            print(f"  OK: FY{fy} inventory = {pct:.1f}% of total assets (plausible)")

    # Check 3: YoY revenue swing sanity check (>50% single-year change = flag for review, not auto-reject)
    cur = conn.execute(
        """SELECT fiscal_year, metric_value FROM financial_metrics
           WHERE metric_name='NetSales' AND extraction_method='manual'
           ORDER BY fiscal_year"""
    )
    rows = cur.fetchall()
    for i in range(1, len(rows)):
        prev_fy, prev_val = rows[i - 1]
        fy, val = rows[i]
        if fy - prev_fy > 3:  # skip if not consecutive-ish years (e.g. 2018 -> 2024 gap)
            continue
        pct_change = (val - prev_val) / prev_val * 100
        if abs(pct_change) > 50:
            print(f"  FLAGGED: NetSales changed {pct_change:+.1f}% from FY{prev_fy} to FY{fy} - unusually large, review before trusting")
            flagged += 1
        else:
            print(f"  OK: NetSales changed {pct_change:+.1f}% from FY{prev_fy} to FY{fy} (plausible)")

    print(f"\nTotal suspicious-value flags raised: {flagged}")
    return flagged


def check_missing_metrics(conn):
    """Flags expected metrics that are missing entirely for a given
    company/year, rather than silently treating them as zero."""
    print("\n=== Missing metric check ===")
    expected_metrics = [
        "NetSales", "CostOfGoodsSold", "GrossProfit", "OperatingIncome",
        "NetIncome", "TotalAssets", "Inventory", "Cash", "TotalLiabilities",
    ]
    cur = conn.execute("SELECT DISTINCT fiscal_year FROM financial_metrics ORDER BY fiscal_year")
    years = [r[0] for r in cur.fetchall()]

    missing_count = 0
    for fy in years:
        cur = conn.execute(
            "SELECT DISTINCT metric_name FROM financial_metrics WHERE fiscal_year=?", (fy,)
        )
        present = {r[0] for r in cur.fetchall()}
        missing = set(expected_metrics) - present
        if missing:
            print(f"  FY{fy}: missing {sorted(missing)} - not backfilled, not guessed, left explicitly absent")
            missing_count += len(missing)
        else:
            print(f"  FY{fy}: all {len(expected_metrics)} expected metrics present")
    print(f"\nTotal missing-metric flags: {missing_count}")


def main():
    conn = sqlite3.connect(DB_PATH)
    check_staleness(conn)
    check_suspicious_values(conn)
    check_missing_metrics(conn)
    conn.close()


if __name__ == "__main__":
    main()
