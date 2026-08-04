"""
backfill_2022_2025.py
---------------------
One-time script: fetches PO + Warehouse data from Salesforce year by year
(2022 -> 2025) and upserts each year into the BigQuery ssl_merged table.

Fetching one year at a time avoids Salesforce QUERY_TIMEOUT.
Uses upsert_by_month so the current 2026 data in BQ is untouched.

Usage:
    python backfill_2022_2025.py
    python backfill_2022_2025.py --years 2022 2023   # specific years only
"""

from __future__ import annotations

import argparse
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
        logging.FileHandler(config.LOGS_DIR / "backfill.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("ssl_dashboard.backfill")


def fetch_year(sf, year: int) -> tuple[Path, Path]:
    """Fetch PO + WH data for one calendar year, save to downloads/ CSVs."""
    start = f"{year}-01-01"
    end   = f"{year}-12-31"
    logger.info("=== Fetching year %d  (%s to %s) ===", year, start, end)

    po_soql = (
        f"SELECT {_PO_SOQL_FIELDS} "
        f"FROM GFERP__Purchase_Line__c "
        f"WHERE CreatedDate >= {start}T00:00:00Z "
        f"AND CreatedDate <= {end}T23:59:59Z "
        f"AND GFERP__Return_Order__c = false"
    )
    wh_soql = (
        f"SELECT {_WH_SOQL_FIELDS} "
        f"FROM GFERP__Whse_Receipt_Line__c "
        f"WHERE CreatedDate >= {start}T00:00:00Z "
        f"AND CreatedDate <= {end}T23:59:59Z "
        f"AND GFERP__Quantity__c > 0"
    )

    po_records = _run_soql(sf, po_soql, f"PO-{year}")
    wh_records = _run_soql(sf, wh_soql, f"WH-{year}")

    po_raw = _flatten_po(po_records)
    wh_raw = _flatten_wh(wh_records)
    logger.info("Year %d raw: PO=%d rows, WH=%d rows", year, len(po_raw), len(wh_raw))

    po_path = config.DOWNLOADS_DIR / f"po_backfill_{year}.csv"
    wh_path = config.DOWNLOADS_DIR / f"wh_backfill_{year}.csv"
    po_raw.to_csv(po_path, index=False, encoding="utf-8")
    wh_raw.to_csv(wh_path, index=False, encoding="utf-8")
    return po_path, wh_path


def process_and_upload(year: int, po_path: Path, wh_path: Path) -> None:
    sheets = data_processor.run_pipeline(po_path, wh_path)
    merged = sheets["Raw_Merged_Data"]
    logger.info("Year %d processed: %d rows", year, len(merged))
    # Use append — historical years (2022-2025) are not yet in BQ, so no dedup needed.
    # append_dataframe avoids DML (DELETE), which is blocked on BQ free tier.
    bigquery_client.append_dataframe(merged, bigquery_client.TABLE_SSL)
    logger.info("Year %d: BigQuery append complete", year)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill SSL data for historical years")
    parser.add_argument("--years", nargs="+", type=int, default=[2022, 2023, 2024, 2025],
                        help="Which years to backfill (default: 2022 2023 2024 2025)")
    args = parser.parse_args()

    logger.info("Starting backfill for years: %s", args.years)
    sf = get_sf_connection()

    for year in sorted(args.years):
        # If CSVs already downloaded from a previous (failed) run, skip the SF fetch
        po_path = config.DOWNLOADS_DIR / f"po_backfill_{year}.csv"
        wh_path = config.DOWNLOADS_DIR / f"wh_backfill_{year}.csv"
        try:
            if po_path.exists() and wh_path.exists():
                logger.info("Year %d: using cached CSVs (skipping SF fetch)", year)
            else:
                po_path, wh_path = fetch_year(sf, year)
            process_and_upload(year, po_path, wh_path)
        except Exception:
            logger.exception("Year %d FAILED — continuing with next year", year)

    logger.info("=== Backfill done ===")


if __name__ == "__main__":
    main()
