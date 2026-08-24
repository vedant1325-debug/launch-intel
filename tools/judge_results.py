"""
Score answer correctness over saved eval results.

Separate from run_evals.py on purpose: judging needs only the question, the
produced answer and the reference, all of which are already in the results file.
Re-running the answers to judge them would spend quota re-deriving what we have.

This is Tier 2 -- advisory. A model judging a model is convenient, not
authoritative. Spot-check before quoting it.
"""
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from google import genai
from run_evals import call_with_retry, judge

client = genai.Client()

for pattern in sys.argv[1:]:
    path = sorted(glob.glob(pattern))[-1]
    data = json.load(open(path))
    rows = [r for r in data["results"]
            if r["expected_behavior"] == "answer" and r["answered"] and r.get("expected")]

    counts = {"match": 0, "partial": 0, "mismatch": 0}
    print(f"\n{'='*62}\n{data['label']}  ({data.get('prompt','strict')} prompt)\n{'='*62}")
    for r in rows:
        j = call_with_retry(judge, client, r["question"], r["answer"], r["expected"])
        counts[j.verdict] = counts.get(j.verdict, 0) + 1
        r["judge"], r["judge_why"] = j.verdict, j.reasoning
        mark = {"match": "ok      ", "partial": "PARTIAL ", "mismatch": "MISMATCH"}[j.verdict]
        print(f"  [{mark}] {r['id']:4} {r['company']:10} {r['answer'][:58]}")
        if j.verdict != "match":
            print(f"             {j.reasoning[:105]}")

    answerable = [x for x in data["results"] if x["expected_behavior"] == "answer"]
    right = counts["match"]
    print(f"\n  correct        {right}/{len(answerable)}  ({right/len(answerable):.0%}) of ALL answerable rows")
    print(f"  breakdown      match={counts['match']} partial={counts['partial']} mismatch={counts['mismatch']}"
          f" refused={len(answerable)-len(rows)}")
    data["judged"] = counts
    Path(path).write_text(json.dumps(data, indent=2))
