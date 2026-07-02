"""
config.py
---------
Central configuration for the SSL Reporting System.
Edit the values below to match your environment — nothing else
in the codebase should need to change for day-to-day use.
"""

from pathlib import Path

# ----------------------------------------------------------------------
# PATHS
# ----------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent

DOWNLOADS_DIR = BASE_DIR / "downloads"          # raw CSVs land here
OUTPUT_DIR = BASE_DIR / "output"                # final SSL_Dashboard.xlsx
LOGS_DIR = BASE_DIR / "logs"
AUTH_DIR = BASE_DIR / "auth"                    # gmail token/credentials

for _d in (DOWNLOADS_DIR, OUTPUT_DIR, LOGS_DIR, AUTH_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Gmail OAuth files (see README for how to obtain credentials.json)
GMAIL_CREDENTIALS_FILE = AUTH_DIR / "credentials.json"
GMAIL_TOKEN_FILE = AUTH_DIR / "token.json"

# If you'd rather drop a shared/network folder copy of the output too,
# set this to a path (e.g. r"\\\\server\\Reports\\SSL") or leave as None.
SHARED_OUTPUT_DIR = None

# ----------------------------------------------------------------------
# SALESFORCE — credentials read from environment variables.
# Local dev:  put values in a .env file (see .env.example).
# Streamlit Cloud: add them in App Settings → Secrets.
# ----------------------------------------------------------------------
import os as _os
SF_USERNAME       = _os.getenv("SF_USERNAME", "")
SF_PASSWORD       = _os.getenv("SF_PASSWORD", "")
SF_SECURITY_TOKEN = _os.getenv("SF_SECURITY_TOKEN", "")
SF_DOMAIN         = _os.getenv("SF_DOMAIN") or None   # None = production, "test" = sandbox
SF_API_VERSION    = "59.0"

# Report IDs — copy from the URL when you open the report in Salesforce
# e.g. https://yourorg.salesforce.com/00O5g000005ABCDEA4
SF_PO_REPORT_ID   = "00OPW00001JLTzd2AH"          # Purchase Order report ID  (00O...)
SF_WH_REPORT_ID   = "00OPW00001Lq6sn2AB"          # Warehouse Receipt report ID (00O...)

SF_FETCH_MONTHS   = 6           # how many calendar months back to pull

# ----------------------------------------------------------------------
# GMAIL SEARCH SETTINGS
# ----------------------------------------------------------------------
# Searches the last 3 days for any CSV-attachment email whose subject
# contains "purchase order" OR "whse" — catches both daily report emails.
GMAIL_SEARCH_QUERY = 'newer_than:3d has:attachment filename:csv subject:"Report results"'

# Email subject keywords (case-insensitive) used to tell the two emails apart.
# The fetcher checks the subject first; falls back to attachment filename if needed.
PO_SUBJECT_HINTS        = ["yr po", "purchase order", "po report"]
WAREHOUSE_SUBJECT_HINTS = ["whse"]

# Attachment filename fallback hints (used only when subject match fails).
PO_FILENAME_HINTS = ["po-", "purchase"]
WAREHOUSE_FILENAME_HINTS = ["warehouse", "receipt", "whse", "rcpt"]

# ----------------------------------------------------------------------
# COLUMN MAPPING
# ----------------------------------------------------------------------
# Maps source CSV column names -> standardized internal names.
# Update the left-hand side ("source name") if your export headers differ.
PO_COLUMN_MAP = {
    "Created Date": "created_date",
    "Purchase Order: Order No.": "po_order_no",
    "Category": "category",
    "Item No.": "item_no",
    "Name": "item_name",
    "Line Status": "line_status",
    "Quantity": "po_qty",
    "Received Qty.": "po_received_qty",       # actual per-line received qty (period in source header)
    "GL Line Cost": "po_value",
    "Preferred Vendor: Account Name": "vendor",
    "Drops Brand: Name": "brand",
    "Expected Receipt Date": "expected_receipt_date",
    "Supplier Code": "supplier_code",
}

WAREHOUSE_COLUMN_MAP = {
    "Item No.": "item_no",
    "Name": "item_name",
    "Quantity": "rec_qty",
    "Line Cost": "rec_value",
    "Unit Cost": "unit_cost",
    "Drops Brand: Name": "brand",
    "Buy-from Vendor": "vendor",
    "Created Date": "created_date",
    "Category": "category",
}

# Required columns after mapping — processing aborts with a clear error
# if any of these are missing post-rename (catches header drift early).
PO_REQUIRED_COLS = [
    "created_date", "item_no", "category", "po_qty", "po_value", "vendor", "brand",
    "po_received_qty",
]
WAREHOUSE_REQUIRED_COLS = [
    "created_date", "item_no", "category", "rec_qty", "rec_value", "vendor", "brand",
]

# Join key (after aggregation)
JOIN_KEYS = ["item_no", "category", "month"]

# ----------------------------------------------------------------------
# OUTPUT
# ----------------------------------------------------------------------
OUTPUT_FILENAME = "SSL_Dashboard.xlsx"
# Set True to also keep a dated copy (SSL_Dashboard_2026-06-30.xlsx) for history
KEEP_DATED_COPY = True

# Brand colors (used lightly in the Excel header styling)
HEADER_FILL_COLOR = "0F1F17"   # dark green
HEADER_FONT_COLOR = "FAF6EF"   # ivory
ACCENT_COLOR = "C9A84C"        # gold
