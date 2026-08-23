"""
Turn the candidate golden set into a spreadsheet you can actually work in.

    python tools/to_csv.py

Writes evals/golden_set.csv. Open it in Numbers, Excel, or Google Sheets, fill
in the `expected` column by reading the real sources, put TRUE in `verified`
for the rows you've checked, then run tools/from_csv.py to convert it back.

Editing JSONL by hand is error-prone -- one stray quote breaks the file and the
error message won't tell you which row. A spreadsheet can't break that way.
"""

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "evals" / "golden_set.candidates.jsonl"
DST = ROOT / "evals" / "golden_set.csv"

# Column order chosen for doing the work, not for the machine: what you're
# looking up, then where to look, then the box you fill in.
COLUMNS = [
    "id",
    "company",
    "category",
    "expected_behavior",
    "question",
    "where_to_look",
    "expected",
    "verified",
]

rows = [json.loads(line) for line in SRC.open() if line.strip()]

with DST.open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=COLUMNS)
    writer.writeheader()
    for row in rows:
        writer.writerow({c: row.get(c, "") for c in COLUMNS})

print(f"Wrote {DST} -- {len(rows)} rows")
print(f"\nOpen it with:  open {DST.relative_to(ROOT)}")
