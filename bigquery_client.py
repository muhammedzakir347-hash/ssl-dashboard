"""
bigquery_client.py
------------------
Thin wrapper around google-cloud-bigquery.

Local:  reads credentials from auth/bq_service_account.json (via BQ_CREDENTIALS_FILE env var)
Cloud:  reads credentials from st.secrets["gcp_service_account"]

Two tables in dataset `ssl_dashboard`:
    ssl_merged        -- SSL pipeline output (what was raw_merged.csv)
    inventory_aging   -- processed inventory aging data
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account

import config

logger = logging.getLogger("ssl_dashboard.bigquery")

PROJECT_ID = "cogent-script-501911-j0"
DATASET    = "ssl_dashboard"
TABLE_SSL  = "ssl_merged"
TABLE_INV  = "inventory_aging"

_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


def _get_credentials():
    # 1. Local: JSON file path from env var or default location
    creds_file = os.getenv("BQ_CREDENTIALS_FILE") or str(config.AUTH_DIR / "bq_service_account.json")
    if Path(creds_file).exists():
        return service_account.Credentials.from_service_account_file(creds_file, scopes=_SCOPES)

    # 2. Streamlit Cloud: credentials stored as TOML table in st.secrets
    try:
        import streamlit as st
        if "gcp_service_account" in st.secrets:
            return service_account.Credentials.from_service_account_info(
                dict(st.secrets["gcp_service_account"]), scopes=_SCOPES
            )
    except Exception:
        pass

    raise FileNotFoundError(
        "BigQuery credentials not found. "
        "Set BQ_CREDENTIALS_FILE env var or add [gcp_service_account] to Streamlit secrets."
    )


def get_client() -> bigquery.Client:
    return bigquery.Client(project=PROJECT_ID, credentials=_get_credentials())


def _safe_col(name: str) -> str:
    """Convert a column name to a BigQuery-safe identifier (letters, digits, underscores)."""
    import re
    return re.sub(r"[^a-zA-Z0-9_]", "_", name).strip("_")


def push_dataframe(df: pd.DataFrame, table: str) -> None:
    """Overwrite a BigQuery table with a DataFrame.
    Column names are sanitized to BQ-safe identifiers automatically.
    """
    client = get_client()
    table_ref = f"{PROJECT_ID}.{DATASET}.{table}"

    # Sanitize column names (BQ rejects spaces, dots, etc.)
    safe_cols = {c: _safe_col(c) for c in df.columns}
    df_safe = df.rename(columns=safe_cols)

    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
    logger.info("BQ push -> %s (%s rows)", table_ref, len(df_safe))
    job = client.load_table_from_dataframe(df_safe, table_ref, job_config=job_config)
    job.result()
    logger.info("BQ push complete -> %s", table_ref)


def read_table(table: str, restore_columns: dict | None = None) -> pd.DataFrame:
    """Read a full BigQuery table into a DataFrame.
    Pass restore_columns={bq_name: original_name} to rename back after read.
    """
    client = get_client()
    query = f"SELECT * FROM `{PROJECT_ID}.{DATASET}.{table}`"
    logger.info("BQ read ← %s", f"{DATASET}.{table}")
    df = client.query(query).to_dataframe()
    if restore_columns:
        df = df.rename(columns=restore_columns)
    logger.info("BQ read complete: %s rows", len(df))
    return df


# Column restore map for inventory_aging (BQ-safe -> original names)
# Keys are what _safe_col() produces: spaces->_ dots->_ then strip leading/trailing _
INV_RESTORE = {
    "Item_No":        "Item No.",
    "Posting_Date":   "Posting Date",
    "Aging_Bucket":   "Aging Bucket",
    "Remaining_Qty":  "Remaining Qty",
    "Unit_Cost":      "Unit Cost",
    "Remaining_Value":"Remaining Value",
}


def table_exists(table: str) -> bool:
    try:
        get_client().get_table(f"{PROJECT_ID}.{DATASET}.{table}")
        return True
    except Exception:
        return False


def get_last_updated(table: str) -> str | None:
    """Return the last-modified time of a BQ table in Kuwait time (UTC+3), or None on failure."""
    try:
        from datetime import timezone, timedelta
        t = get_client().get_table(f"{PROJECT_ID}.{DATASET}.{table}")
        if t.modified:
            kwt = timezone(timedelta(hours=3))
            local_dt = t.modified.astimezone(kwt)
            return local_dt.strftime("%b %d, %Y  %I:%M %p")
    except Exception:
        pass
    return None
