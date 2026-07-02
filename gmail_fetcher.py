"""
gmail_fetcher.py
----------------
Connects to Gmail via the Gmail API (OAuth2 — works fine with Google
Workspace accounts) and downloads today's PO and Warehouse Receipt
CSV attachments into the downloads/ folder.

First-time setup:
    1. Go to https://console.cloud.google.com/ -> create/select a project.
    2. Enable the "Gmail API".
    3. Create OAuth Client ID credentials (type: Desktop app).
    4. Download the JSON and save it as auth/credentials.json.
    5. Run this script once interactively (`python gmail_fetcher.py`) —
       a browser window opens for you to grant access. A token.json is
       then cached in auth/ so future (scheduled, headless) runs don't
       need a browser.

Required pip packages:
    google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import config

logger = logging.getLogger("ssl_dashboard.gmail")

# Read-only access to Gmail is all we need.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def get_gmail_service():
    """Authenticate and return a Gmail API service object."""
    creds: Optional[Credentials] = None

    if config.GMAIL_TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(config.GMAIL_TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired Gmail token")
            creds.refresh(Request())
        else:
            if not config.GMAIL_CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"Missing {config.GMAIL_CREDENTIALS_FILE}. "
                    "Download OAuth client credentials from Google Cloud Console "
                    "and save them there (see gmail_fetcher.py docstring)."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(config.GMAIL_CREDENTIALS_FILE), SCOPES
            )
            # run_local_server requires a browser; fine for the one-time setup run.
            creds = flow.run_local_server(port=0)

        config.GMAIL_TOKEN_FILE.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def _classify_email(subject: str, filename: str) -> Optional[str]:
    """Return 'po', 'warehouse', or None.

    Checks the email subject first (most reliable), then falls back to
    the attachment filename if the subject doesn't match either hint list.
    """
    subj = subject.lower()
    if any(hint in subj for hint in config.PO_SUBJECT_HINTS):
        return "po"
    if any(hint in subj for hint in config.WAREHOUSE_SUBJECT_HINTS):
        return "warehouse"

    # Subject didn't match — try the attachment filename as fallback.
    name = filename.lower()
    if any(hint in name for hint in config.PO_FILENAME_HINTS):
        return "po"
    if any(hint in name for hint in config.WAREHOUSE_FILENAME_HINTS):
        return "warehouse"
    return None


def download_today_attachments() -> dict[str, Path]:
    """
    Searches Gmail for the latest report email and downloads the PO and
    Warehouse CSV attachments.

    Returns:
        dict with keys "po" and "warehouse" mapping to local file paths.

    Raises:
        RuntimeError if either attachment cannot be found.
    """
    service = get_gmail_service()

    logger.info("Searching Gmail with query: %s", config.GMAIL_SEARCH_QUERY)
    results = (
        service.users()
        .messages()
        .list(userId="me", q=config.GMAIL_SEARCH_QUERY, maxResults=10)
        .execute()
    )
    messages = results.get("messages", [])
    if not messages:
        raise RuntimeError(
            "No matching emails found. Check GMAIL_SEARCH_QUERY in config.py "
            "matches the subject/sender of your daily report email."
        )

    found: dict[str, Path] = {}

    # Walk messages newest-first; stop once both files are found.
    for msg_meta in messages:
        if set(found.keys()) >= {"po", "warehouse"}:
            break

        msg = (
            service.users()
            .messages()
            .get(userId="me", id=msg_meta["id"], format="full")
            .execute()
        )

        # Extract subject for classification.
        headers = msg.get("payload", {}).get("headers", [])
        subject = next((h["value"] for h in headers if h["name"].lower() == "subject"), "")
        logger.info("Inspecting email: '%s'", subject)

        parts = msg.get("payload", {}).get("parts", []) or []

        for part in parts:
            filename = part.get("filename")
            if not filename or not filename.lower().endswith(".csv"):
                continue

            kind = _classify_email(subject, filename)
            if kind is None or kind in found:
                continue

            body = part.get("body", {})
            attachment_id = body.get("attachmentId")
            if attachment_id:
                attachment = (
                    service.users()
                    .messages()
                    .attachments()
                    .get(userId="me", messageId=msg_meta["id"], id=attachment_id)
                    .execute()
                )
                data = attachment["data"]
            else:
                data = body.get("data")

            if not data:
                continue

            file_bytes = base64.urlsafe_b64decode(data.encode("UTF-8"))
            dest = config.DOWNLOADS_DIR / f"{kind}_latest.csv"
            dest.write_bytes(file_bytes)
            found[kind] = dest
            logger.info("Downloaded %s attachment -> %s (%.1f KB)", kind, dest, len(file_bytes) / 1024)

    missing = {"po", "warehouse"} - set(found.keys())
    if missing:
        raise RuntimeError(
            f"Could not find attachment(s) for: {', '.join(sorted(missing))}. "
            "Check PO_FILENAME_HINTS / WAREHOUSE_FILENAME_HINTS in config.py "
            "match your actual attachment filenames."
        )

    return found


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    paths = download_today_attachments()
    print("Downloaded files:")
    for kind, path in paths.items():
        print(f"  {kind}: {path}")
