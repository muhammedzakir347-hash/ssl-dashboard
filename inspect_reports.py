"""
inspect_reports.py
------------------
Describe two Salesforce reports so we know what data they contain.
Run:  python inspect_reports.py
"""

import sys
from pathlib import Path
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

sys.path.insert(0, str(Path(__file__).parent))
import salesforce_fetcher as sf_mod

REPORT_IDS = [
    "00OPW00001BxVvN2AV",
    "00OPW00001BxNBR2A3",
]

sf = sf_mod.get_sf_connection()

for rid in REPORT_IDS:
    print(f"\n{'='*60}")
    print(f"Report ID: {rid}")
    print(f"URL: https://dropsgroup.lightning.force.com/lightning/r/Report/{rid}/view")
    print(f"{'='*60}")
    try:
        meta = sf.restful(f"analytics/reports/{rid}/describe")
        info  = meta.get("reportMetadata", {})
        print(f"  Name           : {info.get('name', 'N/A')}")
        print(f"  Report Type    : {info.get('reportType', {}).get('label', 'N/A')}")
        print(f"  Description    : {info.get('description', '(none)')}")
        print(f"  Scope          : {info.get('scope', 'N/A')}")

        # Columns (detail columns are what we'd see in the CSV export)
        cols = info.get("detailColumns", []) or []
        col_meta = meta.get("reportExtendedMetadata", {}).get("detailColumnInfo", {})
        print(f"\n  Columns ({len(cols)}):")
        for c in cols[:30]:
            label = col_meta.get(c, {}).get("label", c)
            dtype = col_meta.get(c, {}).get("dataType", "")
            print(f"    {c:<50s}  {label}  ({dtype})")
        if len(cols) > 30:
            print(f"    ... and {len(cols) - 30} more")

        # Filters
        filters = info.get("reportFilters", [])
        if filters:
            print(f"\n  Filters ({len(filters)}):")
            for f in filters:
                print(f"    {f.get('column','?')} {f.get('operator','?')} {f.get('value','?')}")

    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()

print("\nDone.")
