"""
find_sales_object.py
---------------------
Run this ONCE locally to discover which Salesforce object holds sales data.

Usage:
    python find_sales_object.py

Prints:
  1. All GFERP custom objects whose name contains "Sale" or "Invoice"
  2. A sample query from whichever of these objects has data
"""

import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

sys.path.insert(0, str(Path(__file__).parent))
import config
import salesforce_fetcher as sf_mod

sf = sf_mod.get_sf_connection()

print("\n=== Searching for sale/invoice objects in your Salesforce org ===\n")

# 1. List all custom GFERP objects with 'sale' or 'invoice' in the name
result = sf.mdapi.EntityDefinition.describe()

# simple_salesforce describe gives object list
desc = sf.describe()
objects = desc["sobjects"]

candidates = [
    o["name"] for o in objects
    if ("sale" in o["name"].lower() or "invoice" in o["name"].lower())
    and o["queryable"]
]

print(f"Found {len(candidates)} queryable object(s) with 'sale' or 'invoice' in the name:")
for o in sorted(candidates):
    print(f"  {o}")

print("\n=== Probing each object for recent records ===\n")
for obj in sorted(candidates):
    try:
        q = f"SELECT Id FROM {obj} LIMIT 3"
        r = sf.query(q)
        count = r.get("totalSize", 0)
        print(f"  {obj:60s}  -> {count} sample row(s)  [QUERYABLE]")
    except Exception as e:
        print(f"  {obj:60s}  -> ERROR: {e}")

print("\nDone. Look for the object with rows — that is likely your sales object.")
print("Update _fetch_sales() in salesforce_fetcher.py with the correct name.")
