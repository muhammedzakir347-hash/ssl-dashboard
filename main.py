"""
main.py
-------
Daily entry point. Wires together: Gmail fetch -> data pipeline -> Excel
output. Designed to be triggered by Windows Task Scheduler at 11 PM
(see README.md for the exact scheduler setup).

Usage:
    python main.py                 # fetch from Gmail, then process
    python main.py --local PO.csv WH.csv   # skip Gmail, use local files
                                            # (handy for testing/backfill)
"""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from datetime import datetime
from pathlib import Path

# Load .env so local runs (scheduled task) pick up SF credentials without hardcoding.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

import config
import data_processor
import excel_builder

logger = logging.getLogger("ssl_dashboard.main")


def setup_logging() -> None:
    log_file = config.LOGS_DIR / f"run_{datetime.now():%Y-%m-%d}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Daily SSL Dashboard generator")
    parser.add_argument(
        "--local", nargs=2, metavar=("PO_CSV", "WAREHOUSE_CSV"),
        help="Skip Gmail fetch and use two local CSV files instead.",
    )
    return parser.parse_args()


def get_input_files(args: argparse.Namespace) -> tuple[Path, Path]:
    if args.local:
        po_path, wh_path = Path(args.local[0]), Path(args.local[1])
        for p in (po_path, wh_path):
            if not p.exists():
                raise FileNotFoundError(f"Local file not found: {p}")
        logger.info("Using local files: PO=%s, Warehouse=%s", po_path, wh_path)
        return po_path, wh_path

    # Use Salesforce if credentials are configured (no row-limit), else Gmail.
    if config.SF_USERNAME and config.SF_PO_REPORT_ID and config.SF_WH_REPORT_ID:
        logger.info("Fetching data from Salesforce (SF_USERNAME is set)")
        import salesforce_fetcher
        downloaded = salesforce_fetcher.download_attachments()
    else:
        logger.info("Fetching data from Gmail (Salesforce not configured)")
        import gmail_fetcher
        downloaded = gmail_fetcher.download_today_attachments()

    return downloaded["po"], downloaded["warehouse"]


def main() -> int:
    setup_logging()
    args = parse_args()
    start = datetime.now()
    logger.info("=== SSL Dashboard run started ===")

    try:
        po_path, wh_path = get_input_files(args)
        sheets = data_processor.run_pipeline(po_path, wh_path)

        # Fetch and add inventory aging sheet
        if config.SF_USERNAME and config.SF_INV_REPORT_ID:
            logger.info("Fetching inventory aging data...")
            import salesforce_fetcher
            sf = salesforce_fetcher.get_sf_connection()
            inv_raw = salesforce_fetcher.fetch_inventory(sf)
            inv_path = config.DOWNLOADS_DIR / "inventory_latest.csv"
            inv_raw.to_csv(inv_path, index=False, encoding="utf-8")
            logger.info("Inventory saved -> %s (%s rows)", inv_path, len(inv_raw))
            sheets["Inventory_Aging"] = data_processor.process_inventory_aging(inv_raw)

        saved_paths = excel_builder.save_with_history(sheets)

        # Save local CSV cache (fast fallback when BigQuery is unavailable)
        merged_cache = config.DOWNLOADS_DIR / "raw_merged.csv"
        sheets["Raw_Merged_Data"].to_csv(merged_cache, index=False, encoding="utf-8")
        logger.info("Local cache saved -> %s", merged_cache)

        if "Inventory_Aging" in sheets:
            inv_cache = config.DOWNLOADS_DIR / "inventory_aging.csv"
            sheets["Inventory_Aging"].to_csv(inv_cache, index=False, encoding="utf-8")
            logger.info("Local inventory cache saved -> %s", inv_cache)

        # Push to BigQuery — dashboard reads from here (fast, no SF fetch needed)
        try:
            import bigquery_client
            logger.info("Pushing SSL data to BigQuery...")
            bigquery_client.push_dataframe(sheets["Raw_Merged_Data"], bigquery_client.TABLE_SSL)
            if "Inventory_Aging" in sheets:
                logger.info("Pushing inventory aging to BigQuery...")
                bigquery_client.push_dataframe(sheets["Inventory_Aging"], bigquery_client.TABLE_INV)
            logger.info("BigQuery push complete.")
        except Exception:
            logger.warning("BigQuery push failed (dashboard will use local CSV):\n%s", traceback.format_exc())

        elapsed = (datetime.now() - start).total_seconds()
        logger.info("=== Run completed successfully in %.1fs ===", elapsed)
        for p in saved_paths:
            logger.info("Output: %s", p)
        return 0

    except Exception:
        logger.error("Run FAILED:\n%s", traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
