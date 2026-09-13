"""
find_sales_object.py  — Step 2: describe fields on GFERP__Sales_Invoice_Line__c
Run:  python find_sales_object.py
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

sf = sf_mod.get_sf_connection()

OBJ = "GFERP__Sales_Invoice_Line__c"
print(f"\n=== Fields on {OBJ} ===\n")

fields = sf.__getattr__(OBJ).describe()["fields"]
for f in sorted(fields, key=lambda x: x["name"]):
    print(f"  {f['name']:<55s}  ({f['type']})")

# Also try a sample record to see real values
print(f"\n=== Sample record from {OBJ} ===\n")
field_names = [f["name"] for f in fields if f["type"] not in ("address",)]
# Limit to first 20 fields to keep SOQL short
sample_fields = ", ".join(field_names[:20])
try:
    r = sf.query(f"SELECT {sample_fields} FROM {OBJ} LIMIT 1")
    if r["records"]:
        for k, v in r["records"][0].items():
            if k != "attributes":
                print(f"  {k}: {v}")
    else:
        print("  No records returned.")
except Exception as e:
    print(f"  Sample query error: {e}")
