"""
main.py
-------
Daily entry point. Wires together:
  Salesforce (or Gmail) -> data pipeline -> Excel output -> BigQuery

Triggered by Windows Task Scheduler at 11 PM (see README.md).

Usage:
    python main.py                          # full run (SF preferred, Gmail fallback)
    python main.py --local PO.csv WH.csv   # skip fetch, use local files
    python main.py --no-sales              # skip sales invoice fetch
    python main.py --no-bq                 # skip BigQuery push
"""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from time import perf_counter

import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

import config
import data_processor
import excel_builder

logger = logging.getLogger("ssl_dashboard.main")


# ── Logging ───────────────────────────────────────────────────────────────────
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


# ── Step timer ────────────────────────────────────────────────────────────────
_step_times: list[tuple[str, float, str]] = []   # (label, seconds, status)

@contextmanager
def step(label: str):
    """Log the start/end of a named step with elapsed time."""
    logger.info("── %s …", label)
    t0 = perf_counter()
    status = "OK"
    try:
        yield
    except Exception:
        status = "FAILED"
        raise
    finally:
        elapsed = perf_counter() - t0
        _step_times.append((label, elapsed, status))
        logger.info("   %s done in %.1fs", label, elapsed)


def _summary() -> None:
    """Print a final step-timing table to stdout."""
    print("\n" + "=" * 60)
    print(f"  {'Step':<38} {'Time':>7}  {'Status'}")
    print("  " + "-" * 56)
    total = 0.0
    for label, secs, status in _step_times:
        icon = "✅" if status == "OK" else "❌"
        print(f"  {label:<38} {secs:>6.1f}s  {icon} {status}")
        total += secs
    print("  " + "-" * 56)
    print(f"  {'Total':<38} {total:>6.1f}s")
    print("=" * 60 + "\n")


# ── CLI args ──────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Daily SSL Dashboard generator")
    p.add_argument(
        "--local", nargs=2, metavar=("PO_CSV", "WH_CSV"),
        help="Skip Salesforce/Gmail; use two local CSV files.",
    )
    p.add_argument("--no-sales", action="store_true",
                   help="Skip sales invoice fetch (faster run).")
    p.add_argument("--no-bq",   action="store_true",
                   help="Skip BigQuery push (offline/test run).")
    return p.parse_args()


# ── Data fetch ────────────────────────────────────────────────────────────────
def get_input_files(args: argparse.Namespace) -> tuple[Path, Path]:
    if args.local:
        po_path, wh_path = Path(args.local[0]), Path(args.local[1])
        for p in (po_path, wh_path):
            if not p.exists():
                raise FileNotFoundError(f"Local file not found: {p}")
        logger.info("Using local files: PO=%s, WH=%s", po_path, wh_path)
        return po_path, wh_path

    if config.SF_USERNAME:
        logger.info("Fetching PO + Warehouse from Salesforce …")
        import salesforce_fetcher
        downloaded = salesforce_fetcher.download_attachments()
    else:
        logger.info("Fetching PO + Warehouse from Gmail (Salesforce not configured) …")
        import gmail_fetcher
        downloaded = gmail_fetcher.download_today_attachments()

    return downloaded["po"], downloaded["warehouse"]


# ── Sales aggregation ─────────────────────────────────────────────────────────
def _aggregate_sales(raw: pd.DataFrame) -> pd.DataFrame:
    """Aggregate raw sales lines to Month + Item + Vendor + Brand + Category."""
    s = raw.copy()
    s["Posting Date"] = pd.to_datetime(s["Posting Date"], errors="coerce")
    s["Month"]        = s["Posting Date"].dt.to_period("M").astype(str)
    s["Sales Qty"]    = pd.to_numeric(s["Sales Qty"],   errors="coerce").fillna(0)
    s["Sales Value"]  = pd.to_numeric(s["Sales Value"], errors="coerce").fillna(0)
    return (
        s.groupby(["Month", "Item No.", "Vendor", "Brand", "Category"], dropna=False)
        .agg(Sales_Qty=("Sales Qty", "sum"), Sales_Value=("Sales Value", "sum"))
        .reset_index()
    )


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> int:
    setup_logging()
    args  = parse_args()
    start = datetime.now()
    logger.info("=== SSL Dashboard run started at %s ===", start.strftime("%Y-%m-%d %H:%M"))

    sheets: dict = {}

    try:
        # 1. Fetch PO + Warehouse
        with step("Fetch PO + Warehouse"):
            po_path, wh_path = get_input_files(args)

        # 2. Run SSL pipeline
        with step("SSL pipeline (aggregate + merge)"):
            sheets = data_processor.run_pipeline(po_path, wh_path)
            logger.info("   SSL rows: %s", len(sheets["Raw_Merged_Data"]))

        # 3. Inventory aging (requires SF credentials)
        if config.SF_USERNAME:
            with step("Fetch Inventory Aging (Salesforce)"):
                import salesforce_fetcher
                sf      = salesforce_fetcher.get_sf_connection()
                inv_raw = salesforce_fetcher.fetch_inventory(sf)
                inv_path = config.DOWNLOADS_DIR / "inventory_latest.csv"
                inv_raw.to_csv(inv_path, index=False, encoding="utf-8")
                sheets["Inventory_Aging"] = data_processor.process_inventory_aging(inv_raw)
                logger.info("   Inventory rows: %s", len(inv_raw))

            # 4. Sales invoices (optional)
            if not args.no_sales:
                try:
                    with step("Fetch Sales Invoices (Salesforce)"):
                        sales_raw = salesforce_fetcher.fetch_sales(sf)
                        if not sales_raw.empty:
                            sales_path = config.DOWNLOADS_DIR / "sales_latest.csv"
                            sales_raw.to_csv(sales_path, index=False, encoding="utf-8")
                            sheets["Sales_Data"] = sales_raw
                            logger.info("   Sales rows: %s", len(sales_raw))
                        else:
                            logger.warning("   Sales fetch returned 0 rows.")
                except Exception:
                    logger.warning("Sales fetch skipped (non-fatal):\n%s", traceback.format_exc())
                    _step_times[-1] = (_step_times[-1][0], _step_times[-1][1], "SKIPPED")
            else:
                logger.info("── Sales fetch skipped (--no-sales)")

        # 5. Write Excel
        with step("Write Excel output"):
            saved_paths = excel_builder.save_with_history(sheets)
            for p in saved_paths:
                logger.info("   Saved: %s", p)

        # 6. Save local CSV caches
        with step("Save local CSV caches"):
            sheets["Raw_Merged_Data"].to_csv(
                config.DOWNLOADS_DIR / "raw_merged.csv", index=False, encoding="utf-8"
            )
            if "Inventory_Aging" in sheets:
                sheets["Inventory_Aging"].to_csv(
                    config.DOWNLOADS_DIR / "inventory_aging.csv", index=False, encoding="utf-8"
                )

        # 7. Push to BigQuery
        if not args.no_bq:
            try:
                with step("Push to BigQuery"):
                    import bigquery_client as bq

                    logger.info("   Pushing ssl_merged …")
                    bq.upsert_by_month(sheets["Raw_Merged_Data"], bq.TABLE_SSL)

                    if "Inventory_Aging" in sheets:
                        logger.info("   Pushing inventory_aging …")
                        bq.push_dataframe(sheets["Inventory_Aging"], bq.TABLE_INV)

                    if "Sales_Data" in sheets:
                        logger.info("   Pushing sales_data …")
                        sales_agg = _aggregate_sales(sheets["Sales_Data"])
                        bq.upsert_by_month(sales_agg, bq.TABLE_SALES, month_col="Month")
                        logger.info("   Sales aggregated rows pushed: %s", len(sales_agg))

            except Exception:
                logger.warning("BigQuery push failed (dashboard falls back to local CSV):\n%s",
                               traceback.format_exc())
                _step_times[-1] = (_step_times[-1][0], _step_times[-1][1], "FAILED")
        else:
            logger.info("── BigQuery push skipped (--no-bq)")

        elapsed = (datetime.now() - start).total_seconds()
        logger.info("=== Run completed in %.1fs ===", elapsed)
        _summary()
        return 0

    except Exception:
        logger.error("Run FAILED:\n%s", traceback.format_exc())
        _summary()
        return 1


if __name__ == "__main__":
    sys.exit(main())
