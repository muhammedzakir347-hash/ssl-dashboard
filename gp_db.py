"""
gp_db.py
--------
Loads all downloads/gp/*_gp.csv files into a local DuckDB database
and provides a simple query interface.

Database file: downloads/gp/gp.duckdb   (single file, portable)

Usage:
    # Load / refresh all CSVs into DB
    python gp_db.py --load

    # Run a SQL query and print results
    python gp_db.py --query "SELECT Month, SUM(\"Sales Value (KWD)\") FROM gp GROUP BY Month ORDER BY Month"

    # Export a query to Excel
    python gp_db.py --query "SELECT * FROM gp WHERE Brand = 'Volvic'" --export volvic.xlsx

    # Open interactive SQL shell
    python gp_db.py --shell
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
import pandas as pd

GP_DIR  = Path(__file__).parent / "downloads" / "gp"
DB_FILE = GP_DIR / "gp.duckdb"


def get_conn() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(DB_FILE))


# ── Load ──────────────────────────────────────────────────────────────────────
def load(verbose: bool = True) -> None:
    """Read all *_gp.csv files and (re)create the `gp` table in DuckDB."""
    csv_files = sorted(GP_DIR.glob("*_gp.csv"))
    if not csv_files:
        print(f"ERROR: No *_gp.csv files found in {GP_DIR}")
        sys.exit(1)

    print(f"Loading {len(csv_files)} CSV files into {DB_FILE} ...")
    frames = []
    for f in csv_files:
        df = pd.read_csv(f, encoding="utf-8", parse_dates=["Posting Date"])
        frames.append(df)
        if verbose:
            print(f"  {f.name}: {len(df):,} rows")

    combined = pd.concat(frames, ignore_index=True)
    print(f"  Total: {len(combined):,} rows")

    con = get_conn()
    con.execute("DROP TABLE IF EXISTS gp")
    con.execute("CREATE TABLE gp AS SELECT * FROM combined")
    con.close()

    print(f"\n✅ Loaded into: {DB_FILE}")
    print(f"   Table: gp  |  {len(combined):,} rows  |  {len(combined.columns)} columns")
    print(f"   Columns: {', '.join(combined.columns)}")


# ── Query ─────────────────────────────────────────────────────────────────────
def query(sql: str, export: str | None = None) -> pd.DataFrame:
    """Run SQL and return a DataFrame. Optionally export to Excel."""
    con = get_conn()
    df  = con.execute(sql).df()
    con.close()

    print(f"\n{len(df):,} rows returned")
    print(df.to_string(index=False, max_rows=50))

    if export:
        out = Path(export)
        if not out.is_absolute():
            out = GP_DIR / out
        df.to_excel(out, index=False)
        print(f"\nExported -> {out}")

    return df


# ── Shell ─────────────────────────────────────────────────────────────────────
HELP_TEXT = """
DuckDB GP Shell  (type 'exit' or Ctrl-C to quit, 'help' for examples)

Useful queries:
  -- Monthly totals
  SELECT Month,
         ROUND(SUM("Sales Value (KWD)"), 2) AS Sales,
         ROUND(SUM("COGS (KWD)"), 2)        AS COGS,
         ROUND(SUM("GP (KWD)"), 2)          AS GP,
         ROUND(SUM("GP (KWD)") / SUM("Sales Value (KWD)") * 100, 2) AS "GP%"
  FROM gp GROUP BY Month ORDER BY Month;

  -- Top 20 brands by GP
  SELECT Brand,
         ROUND(SUM("GP (KWD)"), 2)          AS Total_GP,
         ROUND(SUM("Sales Value (KWD)"), 2) AS Total_Sales
  FROM gp GROUP BY Brand ORDER BY Total_GP DESC LIMIT 20;

  -- Daily sales for one brand
  SELECT "Posting Date", SUM("Sales Value (KWD)") AS Sales
  FROM gp WHERE Brand = 'Volvic' GROUP BY "Posting Date" ORDER BY "Posting Date";

  -- All items sold on a specific date
  SELECT * FROM gp WHERE "Posting Date" = '2025-06-15' ORDER BY "GP (KWD)" DESC;

  -- Category GP% ranking
  SELECT Category,
         ROUND(SUM("GP (KWD)") / SUM("Sales Value (KWD)") * 100, 2) AS "GP%"
  FROM gp GROUP BY Category ORDER BY "GP%" DESC;

  -- Export last query result  (append  > filename.xlsx  after a query in --query mode)
"""

def shell() -> None:
    con = get_conn()
    print(HELP_TEXT)
    buf = []
    while True:
        try:
            prompt = "   " if buf else "gp> "
            line = input(prompt)
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if line.strip().lower() in ("exit", "quit", "\\q"):
            print("Bye.")
            break
        if line.strip().lower() == "help":
            print(HELP_TEXT)
            continue

        buf.append(line)
        # Execute when line ends with ;
        if line.rstrip().endswith(";"):
            sql = " ".join(buf).rstrip(";")
            buf = []
            try:
                df = con.execute(sql).df()
                print(f"\n{len(df):,} rows\n")
                print(df.to_string(index=False, max_rows=100))
                print()
            except Exception as e:
                print(f"ERROR: {e}\n")
    con.close()


# ── Info ──────────────────────────────────────────────────────────────────────
def info() -> None:
    con = get_conn()
    try:
        row_count = con.execute("SELECT COUNT(*) FROM gp").fetchone()[0]
        months    = con.execute("SELECT COUNT(DISTINCT Month) FROM gp").fetchone()[0]
        brands    = con.execute("SELECT COUNT(DISTINCT Brand) FROM gp").fetchone()[0]
        items     = con.execute('SELECT COUNT(DISTINCT "Item No.") FROM gp').fetchone()[0]
        min_date  = con.execute('SELECT MIN("Posting Date") FROM gp').fetchone()[0]
        max_date  = con.execute('SELECT MAX("Posting Date") FROM gp').fetchone()[0]
        print(f"""
GP Database: {DB_FILE}
  Rows    : {row_count:,}
  Months  : {months}  ({min_date} → {max_date})
  Brands  : {brands}
  Items   : {items:,}
""")
        summary = con.execute("""
            SELECT Month,
                   ROUND(SUM("Sales Value (KWD)"), 0) AS Sales_KWD,
                   ROUND(SUM("GP (KWD)"), 0)          AS GP_KWD,
                   ROUND(SUM("GP (KWD)") / SUM("Sales Value (KWD)") * 100, 2) AS GP_Pct
            FROM gp GROUP BY Month ORDER BY Month
        """).df()
        print(summary.to_string(index=False))
    except Exception as e:
        print(f"Database not loaded yet: {e}")
        print("Run:  python gp_db.py --load")
    finally:
        con.close()


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    p = argparse.ArgumentParser(description="GP DuckDB — load, query, explore")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--load",  action="store_true", help="Load/refresh CSVs into DB")
    g.add_argument("--query", metavar="SQL",        help="Run a SQL query")
    g.add_argument("--shell", action="store_true",  help="Interactive SQL shell")
    g.add_argument("--info",  action="store_true",  help="Show DB summary stats")
    p.add_argument("--export", metavar="FILE",      help="Export query result to Excel/CSV")
    args = p.parse_args()

    if args.load:
        load()
    elif args.query:
        query(args.query, export=args.export)
    elif args.shell:
        shell()
    else:
        info()


if __name__ == "__main__":
    main()
