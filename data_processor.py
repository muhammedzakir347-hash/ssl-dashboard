"""
data_processor.py
------------------
Core SSL calculation engine. Pure pandas — no Excel/email concerns here,
so it's easy to unit test and reuse (e.g. from a future Streamlit app).

Designed for 200k+ row CSVs:
    - reads only needed columns where possible
    - uses categorical dtypes for groupby keys to cut memory
    - aggregates BEFORE merging (never row-by-row)
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

import config

logger = logging.getLogger("ssl_dashboard.processor")


# ----------------------------------------------------------------------
# LOADING
# ----------------------------------------------------------------------
def _apply_column_map(df: pd.DataFrame, column_map: dict, required_cols: list[str], label: str) -> pd.DataFrame:
    """Rename columns via the config map and validate required columns are present."""
    df = df.copy()
    df.columns = [c.strip() for c in df.columns]

    rename_map = {src: dst for src, dst in column_map.items() if src in df.columns}
    missing_source_cols = [src for src in column_map if src not in df.columns]
    if missing_source_cols:
        logger.warning("%s is missing expected source column(s): %s -- skipping.", label, missing_source_cols)
    df = df.rename(columns=rename_map)

    missing_required = [c for c in required_cols if c not in df.columns]
    if missing_required:
        raise ValueError(
            f"{label} is missing required column(s) after mapping: {missing_required}. "
            f"Check column_map in config.py against the actual file headers."
        )
    return df


def _load_csv(path: Path, column_map: dict, required_cols: list[str], label: str) -> pd.DataFrame:
    logger.info("Reading %s CSV: %s", label, path)
    for _enc in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            df = pd.read_csv(path, dtype=str, low_memory=False, encoding=_enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"Could not decode {path} as utf-8 or cp1252.")

    df = _apply_column_map(df, column_map, required_cols, label)
    logger.info("%s CSV loaded: %s rows, %s cols", label, len(df), len(df.columns))
    return df


def load_po(path: Path) -> pd.DataFrame:
    return _load_csv(path, config.PO_COLUMN_MAP, config.PO_REQUIRED_COLS, "PO")


def load_warehouse(path: Path) -> pd.DataFrame:
    return _load_csv(path, config.WAREHOUSE_COLUMN_MAP, config.WAREHOUSE_REQUIRED_COLS, "Warehouse")


# ----------------------------------------------------------------------
# CLEANING
# ----------------------------------------------------------------------
def _clean_common(df: pd.DataFrame, qty_col: str, value_col: str) -> pd.DataFrame:
    """Standardize key text fields, parse dates/numerics, derive month."""
    df = df.copy()

    for col in ("item_no", "vendor", "brand", "category"):
        if col in df.columns:
            df[col] = (
                df[col]
                .fillna("UNKNOWN")
                .astype(str)
                .str.strip()
                .replace({"": "UNKNOWN", "nan": "UNKNOWN"})
            )

    df["created_date"] = pd.to_datetime(df["created_date"], errors="coerce")
    n_bad_dates = df["created_date"].isna().sum()
    if n_bad_dates:
        logger.warning("Dropping %s rows with unparseable created_date", n_bad_dates)
        df = df[df["created_date"].notna()]

    df["month"] = df["created_date"].dt.to_period("M").astype(str)  # "YYYY-MM"

    df[qty_col] = pd.to_numeric(df[qty_col], errors="coerce").fillna(0.0)
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce").fillna(0.0)

    # Memory optimization: categoricals for low-cardinality grouping keys.
    for col in ("vendor", "brand", "category", "month"):
        df[col] = df[col].astype("category")

    return df


def clean_po(df: pd.DataFrame) -> pd.DataFrame:
    df = _clean_common(df, "po_qty", "po_value")
    if "line_status" in df.columns:
        df["line_status"] = df["line_status"].fillna("UNKNOWN").astype(str).str.strip()
    df["po_received_qty"] = pd.to_numeric(df["po_received_qty"], errors="coerce").fillna(0.0)
    # Received value = pro-rated share of the line cost
    mask = df["po_qty"] > 0
    df["po_received_value"] = 0.0
    df.loc[mask, "po_received_value"] = (
        df.loc[mask, "po_received_qty"] / df.loc[mask, "po_qty"]
    ) * df.loc[mask, "po_value"]
    return df


def clean_warehouse(df: pd.DataFrame) -> pd.DataFrame:
    return _clean_common(df, "rec_qty", "rec_value")


# ----------------------------------------------------------------------
# AGGREGATION
# ----------------------------------------------------------------------
GROUP_COLS = ["item_no", "vendor", "brand", "category", "month"]


PO_GROUP_COLS = ["item_no", "vendor", "brand", "category", "month"]
WH_GROUP_COLS = ["item_no", "vendor", "brand", "category", "month"]


def aggregate_po(df: pd.DataFrame) -> pd.DataFrame:
    agg = (
        df.groupby(PO_GROUP_COLS, observed=True, dropna=False)
        .agg(
            PO_Qty=("po_qty", "sum"),
            PO_Value=("po_value", "sum"),
            Rec_Qty=("po_received_qty", "sum"),
            Rec_Value=("po_received_value", "sum"),
        )
        .reset_index()
    )
    logger.info("PO aggregated to %s rows", len(agg))
    return agg


def aggregate_warehouse(df: pd.DataFrame) -> pd.DataFrame:
    agg = (
        df.groupby(WH_GROUP_COLS, observed=True, dropna=False)
        .agg(Rec_Qty=("rec_qty", "sum"), Rec_Value=("rec_value", "sum"))
        .reset_index()
    )
    logger.info("Warehouse aggregated to %s rows", len(agg))
    return agg


# ----------------------------------------------------------------------
# MERGE + SSL
# ----------------------------------------------------------------------
def build_merged_ssl(po_agg: pd.DataFrame, wh_agg: pd.DataFrame) -> pd.DataFrame:
    # SSL is calculated from PO received qty — already vendor-attributed and accurate.
    # wh_agg is carried through to run_pipeline for the supplemental Warehouse sheet.
    df = po_agg.copy()

    df["SSL_QTY"] = np.where(
        df["PO_Qty"] > 0, (df["Rec_Qty"] / df["PO_Qty"]) * 100, np.nan
    ).round(1)
    df["SSL_VALUE"] = np.where(
        df["PO_Value"] > 0, (df["Rec_Value"] / df["PO_Value"]) * 100, np.nan
    ).round(1)

    df = df[PO_GROUP_COLS + ["PO_Qty", "Rec_Qty", "SSL_QTY", "PO_Value", "Rec_Value", "SSL_VALUE"]]
    df = df.rename(columns={
        "item_no": "Item_No",
        "vendor": "Vendor",
        "brand": "Brand",
        "category": "Category",
        "month": "Month",
    })
    logger.info("SSL dataset: %s rows", len(df))
    return df


# ----------------------------------------------------------------------
# SUMMARY VIEWS
# ----------------------------------------------------------------------
def _weighted_ssl_summary(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    g = (
        df.groupby(group_col, observed=True, dropna=False)
        .agg(
            PO_Qty=("PO_Qty", "sum"),
            Rec_Qty=("Rec_Qty", "sum"),
            PO_Value=("PO_Value", "sum"),
            Rec_Value=("Rec_Value", "sum"),
            Line_Count=("Item_No", "count"),
        )
        .reset_index()
    )
    g["SSL_QTY"] = np.where(g["PO_Qty"] > 0, (g["Rec_Qty"] / g["PO_Qty"]) * 100, np.nan).round(1)
    g["SSL_VALUE"] = np.where(g["PO_Value"] > 0, (g["Rec_Value"] / g["PO_Value"]) * 100, np.nan).round(1)
    return g.sort_values("SSL_VALUE", ascending=True, na_position="first")


def vendor_view(merged: pd.DataFrame) -> pd.DataFrame:
    return _weighted_ssl_summary(merged, "Vendor")


def brand_view(merged: pd.DataFrame) -> pd.DataFrame:
    return _weighted_ssl_summary(merged, "Brand")


def monthly_view(merged: pd.DataFrame) -> pd.DataFrame:
    return _weighted_ssl_summary(merged, "Month").sort_values("Month")


def overall_summary(merged: pd.DataFrame) -> pd.DataFrame:
    """One-row-per-Vendor+Brand+Category summary — good 'pivot-ready' base."""
    summary = (
        merged.groupby(["Vendor", "Brand", "Category"], observed=True, dropna=False)
        .agg(
            PO_Qty=("PO_Qty", "sum"),
            Rec_Qty=("Rec_Qty", "sum"),
            PO_Value=("PO_Value", "sum"),
            Rec_Value=("Rec_Value", "sum"),
        )
        .reset_index()
    )
    summary["SSL_QTY"] = np.where(
        summary["PO_Qty"] > 0, (summary["Rec_Qty"] / summary["PO_Qty"]) * 100, np.nan
    ).round(1)
    summary["SSL_VALUE"] = np.where(
        summary["PO_Value"] > 0, (summary["Rec_Value"] / summary["PO_Value"]) * 100, np.nan
    ).round(1)
    return summary.sort_values("SSL_VALUE", ascending=True, na_position="first")


# ----------------------------------------------------------------------
# INVENTORY AGING
# ----------------------------------------------------------------------
AGING_BINS   = [-1, 30, 60, 90, 120, float("inf")]
AGING_LABELS = ["0-30", "30-60", "60-90", "90-120", "120+"]


def process_inventory_aging(df: pd.DataFrame) -> pd.DataFrame:
    """
    Takes the raw inventory DataFrame from salesforce_fetcher.fetch_inventory()
    and returns a clean aging table with Days and Aging_Bucket columns.
    """
    df = df.copy()

    # Filter to Kuwait only when Country column is present.
    if "Country" in df.columns:
        df = df[df["Country"].str.lower() == "kwt"]
        logger.info("process_inventory_aging: filtered to KWT -> %s rows", len(df))

    # Keep items starting with "KW", excluding "KWP", "KDD", and any gift items.
    upper = df["Item No."].str.upper().fillna("")
    df = df[
        upper.str.startswith("KW") &
        ~upper.str.startswith("KWP") &
        ~upper.str.startswith("KDD") &
        ~upper.str.contains("GIFT")
    ]

    # Exclude specific vendors.
    EXCLUDED_VENDORS = {"EPIC FOOD SUPPLIES CO"}
    df = df[~df["Vendor"].str.upper().isin({v.upper() for v in EXCLUDED_VENDORS})]
    logger.info("process_inventory_aging: after item filter -> %s rows", len(df))

    for col in ("Item No.", "Category", "Brand", "Vendor"):
        df[col] = df[col].fillna("UNKNOWN").astype(str).str.strip().replace({"": "UNKNOWN", "nan": "UNKNOWN"})

    # Optional new columns — fill defaults if not present (e.g. old CSV/BQ data)
    for col in ("Warehouse", "Bin"):
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str).str.strip()

    df["Posting Date"] = pd.to_datetime(df["Posting Date"], errors="coerce")
    df = df[df["Posting Date"].notna()]

    df["Remaining Qty"]  = pd.to_numeric(df["Remaining Qty"],  errors="coerce").fillna(0.0)
    df["Unit Cost"]      = pd.to_numeric(df["Unit Cost"],      errors="coerce").fillna(0.0)
    df["Total Cost"]     = pd.to_numeric(df["Total Cost"],     errors="coerce").fillna(0.0)

    df["Allocated Qty"] = pd.to_numeric(df.get("Allocated Qty"), errors="coerce").fillna(0.0)
    # Available Qty = Remaining Qty when not provided (old data)
    if "Available Qty" in df.columns:
        df["Available Qty"] = pd.to_numeric(df["Available Qty"], errors="coerce").fillna(df["Remaining Qty"])
    else:
        df["Available Qty"] = df["Remaining Qty"]

    today = pd.Timestamp.today().normalize()
    df["Days"] = (today - df["Posting Date"]).dt.days.clip(lower=0)

    df["Aging Bucket"] = pd.cut(df["Days"], bins=AGING_BINS, labels=AGING_LABELS, right=True)

    df["Remaining Value"] = (df["Unit Cost"] * df["Remaining Qty"]).round(2)
    df["Available Value"] = (df["Unit Cost"] * df["Available Qty"]).round(2)

    cols = ["Item No.", "Category", "Brand", "Vendor",
            "Warehouse", "Bin",
            "Posting Date", "Days", "Aging Bucket",
            "Remaining Qty", "Allocated Qty", "Available Qty",
            "Unit Cost", "Remaining Value", "Available Value"]
    return df[cols].sort_values(["Aging Bucket", "Vendor", "Item No."]).reset_index(drop=True)


# ----------------------------------------------------------------------
# PIPELINE ENTRY POINT
# ----------------------------------------------------------------------
def _build_sheets(po_raw: pd.DataFrame, wh_raw: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Core pipeline after data is already cleaned."""
    po_agg = aggregate_po(po_raw)
    wh_agg = aggregate_warehouse(wh_raw)
    merged = build_merged_ssl(po_agg, wh_agg)
    wh_sheet = wh_agg.rename(columns={
        "item_no": "Item_No", "vendor": "Vendor", "brand": "Brand",
        "category": "Category", "month": "Month",
    })
    return {
        "Raw_Merged_Data": merged,
        "SSL_Summary": overall_summary(merged),
        "Vendor_Wise_View": vendor_view(merged),
        "Brand_Wise_View": brand_view(merged),
        "Monthly_Wise_View": monthly_view(merged),
        "Warehouse_Receipts": wh_sheet,
    }


def run_pipeline_from_dfs(po_df: pd.DataFrame, wh_df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Same as run_pipeline but takes raw DataFrames directly (Streamlit Cloud path)."""
    po_raw = clean_po(_apply_column_map(po_df, config.PO_COLUMN_MAP, config.PO_REQUIRED_COLS, "PO"))
    wh_raw = clean_warehouse(_apply_column_map(wh_df, config.WAREHOUSE_COLUMN_MAP, config.WAREHOUSE_REQUIRED_COLS, "Warehouse"))
    return _build_sheets(po_raw, wh_raw)


def run_pipeline(po_csv_path: Path, warehouse_csv_path: Path) -> dict[str, pd.DataFrame]:
    """Runs the full PO + Warehouse -> SSL pipeline and returns all sheets."""
    po_raw = clean_po(load_po(po_csv_path))
    wh_raw = clean_warehouse(load_warehouse(warehouse_csv_path))

    # Warn if either file appears truncated at the ERP export row limit.
    for label, raw in (("PO", po_raw), ("Warehouse", wh_raw)):
        # 14900 = just under the 15000 Salesforce email export cap.
        # Only warn when data came via email (SF direct fetch has no such cap).
        if len(raw) >= 14900 and len(raw) % 2000 == 0:
            logger.warning(
                "%s CSV has %s rows — may be truncated by a 2000-row API cap. "
                "Check Salesforce weekly fetch logs for '[TRUNCATED]' warnings.",
                label, len(raw),
            )
        elif len(raw) == 15000:
            logger.warning(
                "%s CSV has exactly 15000 rows — likely truncated by the email export limit. "
                "Use Salesforce direct fetch (set SF_USERNAME in config.py) to get full data.",
                label,
            )

    return _build_sheets(po_raw, wh_raw)


