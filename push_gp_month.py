"""Push the current month's GP CSV to BigQuery. Called by run_refresh.bat."""
import sys
import datetime
from pathlib import Path

PROJ = Path(__file__).parent
sys.path.insert(0, str(PROJ))

from dotenv import load_dotenv
load_dotenv(PROJ / ".env")

import pandas as pd
import bigquery_client as bq

month = datetime.date.today().strftime("%Y-%m")
csv = PROJ / "downloads" / "gp" / f"{month}_gp.csv"

if not csv.exists():
    print(f"GP CSV not found: {csv} — skipping BQ push.")
    sys.exit(0)

df = pd.read_csv(csv)
df["Month"] = month
print(f"GP push: {len(df):,} rows for {month} → BigQuery ...")
bq.upsert_by_month(df, bq.TABLE_GP, month_col="Month")
print("GP BQ push done.")
