"""
salesforce_fetcher.py
---------------------
Fetches PO and Warehouse Receipt data directly from Salesforce using SOQL
with automatic pagination — no row-count cap.

How it works:
  1. Authenticates with username + password + security token.
  2. Runs SOQL queries on the underlying custom objects (GFERP__Purchase_Line__c
     and GFERP__Whse_Receipt_Line__c) with a date-range filter.
  3. simple_salesforce.query_all() auto-paginates through all result pages.
  4. Flattens nested relationship fields into a flat DataFrame whose column
     names match the report column labels already in config.PO_COLUMN_MAP /
     config.WAREHOUSE_COLUMN_MAP — no changes to the rest of the pipeline.
  5. Saves CSV files to downloads/ so main.py can pass them to data_processor.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date
from pathlib import Path

import pandas as pd
from dateutil.relativedelta import relativedelta
from simple_salesforce import Salesforce
from simple_salesforce.exceptions import SalesforceAuthenticationFailed

import config

logger = logging.getLogger("ssl_dashboard.salesforce")

# Retry config for transient SOQL failures (network blip, temp timeout).
# Auth failures are NEVER retried — repeated wrong-credential attempts freeze the account.
_SOQL_RETRY_WAITS = [30, 90]  # seconds between attempts 1→2 and 2→3

# -------------------------------------------------------------------------
# AUTH BACKOFF
# After one auth failure we write a timestamp file and refuse any further
# Salesforce connections for _AUTH_BACKOFF_SECS seconds.  This stops a
# broken scheduler or repeated page loads from piling up failed logins.
# -------------------------------------------------------------------------
_AUTH_BACKOFF_FILE = config.LOGS_DIR / ".sf_auth_backoff"
_AUTH_BACKOFF_SECS = 7200   # 2 hours


def _in_auth_backoff() -> bool:
    """Return True (and log a warning) if we're still inside the backoff window."""
    if not _AUTH_BACKOFF_FILE.exists():
        return False
    try:
        data = json.loads(_AUTH_BACKOFF_FILE.read_text(encoding="utf-8"))
        elapsed = time.time() - data.get("failed_at", 0)
        if elapsed < _AUTH_BACKOFF_SECS:
            remaining = int(_AUTH_BACKOFF_SECS - elapsed)
            logger.warning(
                "Salesforce auth is in backoff after a recent failure. "
                "Skipping connection for another %d min to protect the account. "
                "Fix credentials then delete %s to unblock immediately.",
                remaining // 60, _AUTH_BACKOFF_FILE,
            )
            return True
        _AUTH_BACKOFF_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    return False


def _set_auth_backoff() -> None:
    try:
        _AUTH_BACKOFF_FILE.write_text(
            json.dumps({"failed_at": time.time()}), encoding="utf-8"
        )
        logger.error(
            "Auth backoff set for %d min. No Salesforce connections will be attempted "
            "until then. Fix credentials and delete %s to unblock early.",
            _AUTH_BACKOFF_SECS // 60, _AUTH_BACKOFF_FILE,
        )
    except Exception as exc:
        logger.warning("Could not write auth backoff file: %s", exc)


def _clear_auth_backoff() -> None:
    try:
        _AUTH_BACKOFF_FILE.unlink(missing_ok=True)
    except Exception:
        pass


# -------------------------------------------------------------------------
# CONNECTION
# -------------------------------------------------------------------------
def get_sf_connection() -> Salesforce:
    missing = [k for k in ("SF_USERNAME", "SF_PASSWORD", "SF_SECURITY_TOKEN") if not getattr(config, k, "")]
    if missing:
        raise ValueError(
            f"Salesforce credentials not set in config.py: {missing}. "
            "See salesforce_fetcher.py docstring for setup instructions."
        )
    if _in_auth_backoff():
        raise RuntimeError(
            f"Salesforce auth is blocked for up to {_AUTH_BACKOFF_SECS // 60} min "
            f"after a recent failure. Delete {_AUTH_BACKOFF_FILE} to unblock early."
        )
    domain_label = config.SF_DOMAIN or "production"
    logger.info("Connecting to Salesforce as %s (%s)", config.SF_USERNAME, domain_label)
    try:
        sf = Salesforce(
            username=config.SF_USERNAME,
            password=config.SF_PASSWORD,
            security_token=config.SF_SECURITY_TOKEN,
            domain=config.SF_DOMAIN,
        )
    except SalesforceAuthenticationFailed as exc:
        _set_auth_backoff()
        logger.error(
            "Salesforce authentication FAILED — wrong password or security token. "
            "NOT retrying. Error: %s", exc,
        )
        raise
    _clear_auth_backoff()
    logger.info("Connected. Instance: %s", sf.sf_instance)
    return sf


# -------------------------------------------------------------------------
# SOQL QUERIES
# -------------------------------------------------------------------------
# PO fields to select — column names match config.PO_COLUMN_MAP labels exactly.
_PO_SOQL_FIELDS = (
    "CreatedDate, "
    "GFERP__Purchase_Order__r.Name, "
    "GFERP__Item__r.Category__c, "
    "GFERP__Item__r.Name, "
    "Name, "
    "GFERP__Line_Status__c, "
    "GFERP__Quantity__c, "
    "GFERP__Received_Qty__c, "
    "GFERP__GL_Line_Cost__c, "
    "GFERP__Item__r.GFERP__Vendor__r.Name, "
    "GFERP__Item__r.Drops_Brand__r.Name, "
    "GFERP__Expected_Receipt_Date__c, "
    "GFERP__Item__r.Supplier_Code__c"
)

_WH_SOQL_FIELDS = (
    "GFERP__Item__r.Name, "
    "Name, "
    "GFERP__Quantity__c, "
    "GFERP__Line_Cost__c, "
    "GFERP__Unit_Cost__c, "
    "GFERP__Item__r.Drops_Brand__r.Name, "
    "GFERP__Buy_from_Vendor__c, "
    "CreatedDate, "
    "GFERP__Item__r.Category__c"
)


def _flatten_po(records: list[dict]) -> pd.DataFrame:
    """Flatten SOQL records for GFERP__Purchase_Line__c into the report column labels."""
    rows = []
    for r in records:
        item      = r.get("GFERP__Item__r") or {}
        vendor_rel = item.get("GFERP__Vendor__r") or {}
        brand_rel  = item.get("Drops_Brand__r") or {}
        po_rel     = r.get("GFERP__Purchase_Order__r") or {}
        rows.append({
            "Created Date":                   r.get("CreatedDate"),
            "Purchase Order: Order No.":      po_rel.get("Name"),
            "Category":                       item.get("Category__c"),
            "Item No.":                       item.get("Name"),
            "Name":                           r.get("Name"),
            "Line Status":                    r.get("GFERP__Line_Status__c"),
            "Quantity":                       r.get("GFERP__Quantity__c"),
            "Received Qty.":                  r.get("GFERP__Received_Qty__c"),
            "GL Line Cost":                   r.get("GFERP__GL_Line_Cost__c"),
            "Preferred Vendor: Account Name": vendor_rel.get("Name"),
            "Drops Brand: Name":              brand_rel.get("Name"),
            "Expected Receipt Date":          r.get("GFERP__Expected_Receipt_Date__c"),
            "Supplier Code":                  item.get("Supplier_Code__c"),
        })
    return pd.DataFrame(rows)


def _flatten_wh(records: list[dict]) -> pd.DataFrame:
    """Flatten SOQL records for GFERP__Whse_Receipt_Line__c into the report column labels."""
    rows = []
    for r in records:
        item      = r.get("GFERP__Item__r") or {}
        brand_rel = item.get("Drops_Brand__r") or {}
        rows.append({
            "Item No.":          item.get("Name"),
            "Name":              r.get("Name"),
            "Quantity":          r.get("GFERP__Quantity__c"),
            "Line Cost":         r.get("GFERP__Line_Cost__c"),
            "Unit Cost":         r.get("GFERP__Unit_Cost__c"),
            "Drops Brand: Name": brand_rel.get("Name"),
            "Buy-from Vendor":   r.get("GFERP__Buy_from_Vendor__c"),
            "Created Date":      r.get("CreatedDate"),
            "Category":          item.get("Category__c"),
        })
    return pd.DataFrame(rows)


# -------------------------------------------------------------------------
# FETCH HELPERS
# -------------------------------------------------------------------------
def _date_range() -> tuple[str, str]:
    today      = date.today()
    start_date = (today - relativedelta(months=config.SF_FETCH_MONTHS - 1)).replace(day=1)
    return str(start_date), str(today)


def _run_soql(sf: Salesforce, soql: str, label: str) -> list[dict]:
    last_exc: Exception | None = None
    for attempt, wait in enumerate(["first"] + _SOQL_RETRY_WAITS, start=1):
        if attempt > 1:
            logger.warning("%s: transient error — retrying in %ss (attempt %d)…", label, wait, attempt)
            time.sleep(wait)
        try:
            logger.info("%s: SOQL attempt %d …", label, attempt)
            result  = sf.query_all(soql)
            records = result.get("records", [])
            logger.info("%s: %s rows fetched", label, len(records))
            return records
        except SalesforceAuthenticationFailed as exc:
            # Wrong credentials — retrying will only pile up failed logins and freeze the account.
            logger.error("%s: auth failed — NOT retrying: %s", label, exc)
            raise
        except Exception as exc:
            last_exc = exc
            logger.warning("%s: attempt %d failed: %s", label, attempt, exc)
    logger.error("%s: all attempts exhausted. Last error: %s", label, last_exc)
    raise last_exc  # type: ignore[misc]


def _fetch_po(sf: Salesforce) -> pd.DataFrame:
    start, end = _date_range()
    soql = (
        f"SELECT {_PO_SOQL_FIELDS} "
        f"FROM GFERP__Purchase_Line__c "
        f"WHERE CreatedDate >= {start}T00:00:00Z "
        f"AND CreatedDate <= {end}T23:59:59Z "
        f"AND GFERP__Return_Order__c = false"
    )
    records = _run_soql(sf, soql, "PO")
    df = _flatten_po(records)
    logger.info("PO DataFrame: %s rows x %s cols", len(df), len(df.columns))
    return df


def _fetch_wh(sf: Salesforce) -> pd.DataFrame:
    start, end = _date_range()
    soql = (
        f"SELECT {_WH_SOQL_FIELDS} "
        f"FROM GFERP__Whse_Receipt_Line__c "
        f"WHERE CreatedDate >= {start}T00:00:00Z "
        f"AND CreatedDate <= {end}T23:59:59Z "
        f"AND GFERP__Quantity__c > 0"
    )
    records = _run_soql(sf, soql, "Warehouse")
    df = _flatten_wh(records)
    logger.info("Warehouse DataFrame: %s rows x %s cols", len(df), len(df.columns))
    return df


_INV_SOQL_FIELDS = (
    "GFERP__Item__r.Name, "
    "GFERP__Item__r.Category__c, "
    "GFERP__Item__r.Drops_Brand__r.Name, "
    "GFERP__Item__r.GFERP__Vendor__r.Name, "
    "GFERP__Item__r.Country__c, "
    "GFERP__Bin__r.Name, "
    "GFERP__Warehouse__r.Name, "
    "GFERP__Posting_Date__c, "
    "GFERP__Unit_Cost__c, "
    "GFERP__Remaining_Qty_Base__c, "
    "GFERP__Allocated_Qty_Base__c, "
    "GFERP__Available_Qty_Base__c, "
    "GFERP__Total_Cost__c"
)


def _flatten_inv(records: list[dict]) -> pd.DataFrame:
    rows = []
    for r in records:
        item       = r.get("GFERP__Item__r") or {}
        brand_rel  = item.get("Drops_Brand__r") or {}
        vendor_rel = item.get("GFERP__Vendor__r") or {}
        bin_rel    = r.get("GFERP__Bin__r") or {}
        wh_rel     = r.get("GFERP__Warehouse__r") or {}
        rows.append({
            "Item No.":       item.get("Name"),
            "Category":       item.get("Category__c"),
            "Brand":          brand_rel.get("Name"),
            "Vendor":         vendor_rel.get("Name"),
            "Country":        item.get("Country__c"),
            "Warehouse":      wh_rel.get("Name"),
            "Bin":            bin_rel.get("Name"),
            "Posting Date":   r.get("GFERP__Posting_Date__c"),
            "Unit Cost":      r.get("GFERP__Unit_Cost__c"),
            "Remaining Qty":  r.get("GFERP__Remaining_Qty_Base__c"),
            "Allocated Qty":  r.get("GFERP__Allocated_Qty_Base__c"),
            "Available Qty":  r.get("GFERP__Available_Qty_Base__c"),
            "Total Cost":     r.get("GFERP__Total_Cost__c"),
        })
    return pd.DataFrame(rows)


def fetch_inventory(sf: Salesforce | None = None) -> pd.DataFrame:
    """Fetch Kuwait inventory aging data from GFERP__Item_Ledger_Entry__c."""
    if sf is None:
        sf = get_sf_connection()
    # Push country + qty filters into SOQL so Salesforce scans fewer rows.
    # - GFERP__Item__r.Country__c = 'kwt'  →  drops ~35% non-KWT records before transfer
    # - GFERP__Remaining_Qty_Base__c > 0   →  standard stock filter (index-friendly)
    # SOQL string comparisons are case-insensitive so 'kwt' matches 'KWT' / 'Kwt'.
    # Python post-filter kept as a safety net for any edge cases.
    soql = (
        f"SELECT {_INV_SOQL_FIELDS} "
        f"FROM GFERP__Item_Ledger_Entry__c "
        f"WHERE GFERP__Item__r.Country__c = 'kwt' "
        f"AND GFERP__Remaining_Qty_Base__c > 0"
    )
    records = _run_soql(sf, soql, "Inventory")
    df = _flatten_inv(records)
    before = len(df)
    df = df[df["Country"].str.lower() == "kwt"]
    logger.info("Inventory: %s KWT rows (dropped %s non-KWT)", len(df), before - len(df))

    # Keep items starting with "KW", excluding "KWP", "KDD", and any gift items.
    upper = df["Item No."].str.upper().fillna("")
    before = len(df)
    df = df[
        upper.str.startswith("KW") &
        ~upper.str.startswith("KWP") &
        ~upper.str.startswith("KDD") &
        ~upper.str.contains("GIFT")
    ]
    logger.info("Inventory: %s rows after item filter (dropped %s)", len(df), before - len(df))

    # Exclude specific vendors.
    EXCLUDED_VENDORS = {"EPIC FOOD SUPPLIES CO"}
    before = len(df)
    df = df[~df["Vendor"].str.upper().isin({v.upper() for v in EXCLUDED_VENDORS})]
    logger.info("Inventory: %s rows after vendor exclusion (dropped %s)", len(df), before - len(df))
    return df


# -------------------------------------------------------------------------
# PUBLIC ENTRY POINTS
# -------------------------------------------------------------------------
def _fetch_both(sf: Salesforce) -> dict[str, pd.DataFrame]:
    """Authenticate once, pull both reports, return as DataFrames."""
    start, end = _date_range()
    logger.info("Date range: %s to %s (%s months)", start, end, config.SF_FETCH_MONTHS)
    return {
        "po":        _fetch_po(sf),
        "warehouse": _fetch_wh(sf),
    }


def fetch_dataframes() -> dict[str, pd.DataFrame]:
    """
    Fetch PO and Warehouse data directly into memory -- no CSV written to disk.
    Returns {'po': DataFrame, 'warehouse': DataFrame}.
    """
    return _fetch_both(get_sf_connection())


def download_attachments() -> dict[str, Path]:
    """
    Fetch and save to downloads/ as CSV files.
    Returns {'po': Path, 'warehouse': Path} -- same contract as
    gmail_fetcher.download_today_attachments().
    """
    sf     = get_sf_connection()
    frames = _fetch_both(sf)
    result: dict[str, Path] = {}
    for kind, df in frames.items():
        dest = config.DOWNLOADS_DIR / f"{kind}_latest.csv"
        df.to_csv(dest, index=False, encoding="utf-8")
        logger.info("%s saved -> %s (%s rows)", kind, dest, len(df))
        result[kind] = dest
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    paths = download_attachments()
    print("Downloaded:")
    for kind, path in paths.items():
        print(f"  {kind}: {path}")
