"""
Convert your filled-in spreadsheet back into the golden set.

    python tools/from_csv.py

Reads evals/golden_set.csv, checks it over, writes evals/golden_set.jsonl.

The checks matter more than the conversion. It refuses to write a set that would
give you a misleading score, and tells you exactly which rows are the problem.
"""

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "evals" / "golden_set.csv"
DST = ROOT / "evals" / "golden_set.jsonl"

TRUTHY = {"true", "yes", "y", "1", "x", "done"}

if not SRC.exists():
    sys.exit(f"No {SRC}. Run tools/to_csv.py first.")

rows = list(csv.DictReader(SRC.open()))

kept, problems, skipped = [], [], []

for row in rows:
    verified = row.get("verified", "").strip().lower() in TRUTHY
    expected = row.get("expected", "").strip()
    behavior = row.get("expected_behavior", "").strip()
    rid = row.get("id", "?")

    if not verified:
        skipped.append(rid)
        continue

    # A verified row with no expected answer is the dangerous case: it looks
    # scored but has nothing to score against, so it would silently inflate or
    # deflate your accuracy depending on how the runner treats a blank.
    if behavior == "answer" and not expected:
        problems.append(f"{rid}: marked verified but `expected` is empty")
        continue

    kept.append(
        {
            "id": rid,
            "company": row.get("company", "").strip(),
            "category": row.get("category", "").strip(),
            "expected_behavior": behavior,
            "question": row.get("question", "").strip(),
            "where_to_look": row.get("where_to_look", "").strip(),
            "expected": expected,
            "verified": True,
        }
    )

if problems:
    print("Problems -- fix these in the spreadsheet and re-run:\n")
    for p in problems:
        print(f"  {p}")
    sys.exit(1)

refusals = sum(1 for r in kept if r["expected_behavior"] == "refuse")
answers = len(kept) - refusals

with DST.open("w") as f:
    for row in kept:
        f.write(json.dumps(row) + "\n")

print(f"Wrote {DST} -- {len(kept)} verified rows ({answers} answer, {refusals} refuse)")
if skipped:
    print(f"Skipped {len(skipped)} unverified: {', '.join(skipped)}")

# These aren't errors, but a set that trips them will mislead you, so say so.
if refusals < 5:
    print(
        f"\nWARNING: only {refusals} refusal rows. Below ~5 the eval stops "
        "punishing confident fabrication, which is the failure you're measuring."
    )
if answers < 15:
    print(
        f"\nWARNING: only {answers} answerable rows. Citation accuracy over a "
        "set this small swings a lot on single claims."
    )
