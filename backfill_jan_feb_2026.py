"""
backfill_jan_feb_2026.py
------------------------
One-time script: fills the gap between the 2022-2025 historical backfill
and the 6-month rolling window (which starts March 2026).

Fetches PO + Warehouse data for Jan 1 – Feb 28, 2026 from Salesforce
and upserts into BigQuery using upsert_by_month (safe — won't duplicate
any existing months).

Usage:
    python backfill_jan_feb_2026.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

import config
import bigquery_client
import data_processor
from salesforce_fetcher import (
    _PO_SOQL_FIELDS,
    _WH_SOQL_FIELDS,
    _flatten_po,
    _flatten_wh,
    _run_soql,
    get_sf_connection,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(config.LOGS_DIR / "backfill_jan_feb_2026.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("ssl_dashboard.backfill_jan_feb_2026")

START = "2026-01-01"
END   = "2026-02-28"


def main() -> None:
    logger.info("=== Backfill Jan-Feb 2026 started (%s to %s) ===", START, END)

    po_cache  = config.DOWNLOADS_DIR / "po_backfill_jan_feb_2026.csv"
    wh_cache  = config.DOWNLOADS_DIR / "wh_backfill_jan_feb_2026.csv"

    # ── 1. Fetch from Salesforce (or reuse cached CSVs) ──────────────────
    if po_cache.exists() and wh_cache.exists():
        logger.info("Using cached CSVs — skipping Salesforce fetch")
    else:
        sf = get_sf_connection()

        po_soql = (
            f"SELECT {_PO_SOQL_FIELDS} "
            f"FROM GFERP__Purchase_Line__c "
            f"WHERE CreatedDate >= {START}T00:00:00Z "
            f"AND CreatedDate <= {END}T23:59:59Z "
            f"AND GFERP__Return_Order__c = false"
        )
        wh_soql = (
            f"SELECT {_WH_SOQL_FIELDS} "
            f"FROM GFERP__Whse_Receipt_Line__c "
            f"WHERE CreatedDate >= {START}T00:00:00Z "
            f"AND CreatedDate <= {END}T23:59:59Z "
            f"AND GFERP__Quantity__c > 0"
        )

        po_records = _run_soql(sf, po_soql, "PO-Jan-Feb-2026")
        wh_records = _run_soql(sf, wh_soql, "WH-Jan-Feb-2026")

        po_raw = _flatten_po(po_records)
        wh_raw = _flatten_wh(wh_records)
        logger.info("Fetched: PO=%d rows, WH=%d rows", len(po_raw), len(wh_raw))

        po_raw.to_csv(po_cache, index=False, encoding="utf-8")
        wh_raw.to_csv(wh_cache, index=False, encoding="utf-8")
        logger.info("CSVs saved -> %s, %s", po_cache, wh_cache)

    # ── 2. Process through the normal pipeline ────────────────────────────
    sheets = data_processor.run_pipeline(po_cache, wh_cache)
    merged = sheets["Raw_Merged_Data"]
    logger.info("Processed: %d rows", len(merged))

    months = sorted(merged["Month"].dropna().unique())
    logger.info("Months in data: %s", months)

    # ── 3. Upsert into BigQuery (safe — skips months already present) ─────
    # upsert_by_month replaces rows only for months in `merged`,
    # so existing 2022-2025 and Mar-Aug 2026 data are untouched.
    bigquery_client.upsert_by_month(merged, bigquery_client.TABLE_SSL)
    logger.info("=== BigQuery upsert complete. Jan-Feb 2026 gap is filled. ===")


if __name__ == "__main__":
    main()
