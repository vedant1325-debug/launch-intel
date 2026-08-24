"""
Score the system against the golden set.

Run this on Day 5 (before verification is wired in) and again on Day 10 (after).
The gap between the two runs is the result the whole project is built to produce.
For that comparison to mean anything, both runs must use the same golden set and
the same cached sources -- so this never re-fetches pages.

Two tiers of metric, and the distinction matters.

TIER 1 -- objective. No judgement, no second model, nothing to argue with:

    False refusal rate   of the answerable rows, how many did it decline?
    Fabrication rate     of the unanswerable rows, how many did it answer?

Both come straight from the `answered` boolean. These are the headline numbers
because nobody can dispute them, and because they capture the real tension: any
prompt change that pushes one down tends to push the other up. Where you choose
to sit on that curve is the product decision.

TIER 2 -- needs judgement. Of the answers it did give, how many were actually
right? Scored by a second model with --judge, which is convenient and NOT
authoritative. Spot-check it by hand before quoting it anywhere.

A note on sample size: with ~12 answerable rows, one row is worth ~8 points.
Treat small movements as noise. Only a large swing means anything here, and
saying so in the write-up is better than pretending to precision you lack.
"""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from google import genai
from pydantic import BaseModel, Field

from research import ANSWER_SYSTEM, ANSWER_SYSTEM_LOOSE, answer_question, get_sources
from verify import SYNTHESIS_MODEL, VERIFIER_MODEL, TokenUsage, estimate_cost

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "evals" / "golden_set.jsonl"
RESULTS = ROOT / "evals" / "results"


class Judgement(BaseModel):
    """Whether a produced answer matches the reference answer."""

    verdict: str = Field(description="One of: match, partial, mismatch.")
    reasoning: str = Field(description="One sentence.")


JUDGE_SYSTEM = """\
You compare a produced answer against a reference answer to the same question.

Judge meaning, not wording. Different phrasing of the same fact is a match.

- match     -- same fact, however phrased
- partial   -- overlapping but missing or adding something material
- mismatch  -- a different fact, or contradicts the reference

Numbers must agree to count as a match. $16 and $16/user/month billed yearly are
the same fact; $16 and $10 are not. If the reference is vague and the produced
answer is specific and consistent with it, that is a match, not a partial."""


def call_with_retry(fn, *args, attempts: int = 4, **kwargs):
    """Free-tier rate limits are per-minute, so a 429 usually just means wait.

    Retrying is not papering over a bug here -- a run of 19 questions back to
    back will legitimately trip a per-minute cap partway through, and losing the
    whole run to that would be worse than pausing.
    """
    for i in range(attempts):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            if "429" not in str(exc) and "RESOURCE_EXHAUSTED" not in str(exc):
                raise
            if i == attempts - 1:
                raise
            wait = 20 * (i + 1)
            print(f"      rate limited, waiting {wait}s...")
            time.sleep(wait)


def judge(client, question: str, produced: str, reference: str) -> Judgement:
    interaction = client.interactions.create(
        model=VERIFIER_MODEL,
        system_instruction=JUDGE_SYSTEM,
        input=(
            f"Question: {question}\n\n"
            f"Reference answer: {reference}\n\n"
            f"Produced answer: {produced}"
        ),
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": Judgement.model_json_schema(),
        },
    )
    return Judgement.model_validate_json(interaction.output_text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Score the system against the golden set.")
    parser.add_argument("--judge", action="store_true",
                        help="Also score answer correctness with a second model (advisory).")
    parser.add_argument("--label", default="baseline",
                        help="Name for this run, e.g. baseline or verified.")
    # The free tier caps gemini-3.7-flash at 20 requests/day, which a single eval
    # run exceeds. flash-lite has a workable allowance, so it is the default here.
    # Re-running with --model gemini-3.7-flash once quota resets gives the
    # cheap-vs-capable comparison the Day 12 table needs, on identical questions.
    parser.add_argument("--prompt", choices=["strict", "loose"], default="strict",
                        help="Which answering prompt to test.")
    parser.add_argument("--model", default=VERIFIER_MODEL,
                        help="Model to answer with. Default flash-lite (free-tier quota).")
    args = parser.parse_args()

    rows = [json.loads(line) for line in GOLDEN.open() if line.strip()]
    client = genai.Client()
    results, cost = [], 0.0

    print(f"Scoring {len(rows)} rows with {args.model}...\n")
    for row in rows:
        sources = get_sources(row["company"])          # cached; never re-fetches
        ans, usage = call_with_retry(
            answer_question, client, row["company"], row["question"], sources,
            model=args.model,
            system=ANSWER_SYSTEM_LOOSE if args.prompt == "loose" else ANSWER_SYSTEM,
        )
        cost += estimate_cost(args.model, usage)

        should_answer = row["expected_behavior"] == "answer"
        # The two Tier 1 failures. Both are pure booleans -- no judgement.
        false_refusal = should_answer and not ans.answered
        fabrication = (not should_answer) and ans.answered
        ok = not (false_refusal or fabrication)

        rec = {
            "id": row["id"], "company": row["company"],
            "question": row["question"], "expected_behavior": row["expected_behavior"],
            "expected": row.get("expected", ""),
            "answered": ans.answered, "answer": ans.answer,
            "source_ids": ans.source_ids, "reasoning": ans.reasoning,
            "false_refusal": false_refusal, "fabrication": fabrication,
        }

        if args.judge and ans.answered and should_answer and row.get("expected"):
            j = call_with_retry(judge, client, row["question"], ans.answer, row["expected"])
            rec["judge"] = j.verdict
            rec["judge_why"] = j.reasoning

        results.append(rec)
        flag = "ok  " if ok else ("FALSE-REFUSAL" if false_refusal else "FABRICATION ")
        extra = f"  judge={rec.get('judge','-')}" if args.judge else ""
        print(f"  [{flag}] {row['id']:4} {row['company']:12} "
              f"{'answered' if ans.answered else 'refused ':9}{extra}")

    answerable = [r for r in results if r["expected_behavior"] == "answer"]
    unanswerable = [r for r in results if r["expected_behavior"] == "refuse"]
    fr = sum(r["false_refusal"] for r in answerable)
    fab = sum(r["fabrication"] for r in unanswerable)

    print("\n" + "=" * 58)
    print(f"RESULTS -- {args.label}  ({args.model}, {args.prompt} prompt)")
    print("=" * 58)
    print("\nTier 1 (objective)")
    print(f"  False refusal   {fr}/{len(answerable):<3} "
          f"({fr/len(answerable):.0%})  refused an answerable question")
    print(f"  Fabrication     {fab}/{len(unanswerable):<3} "
          f"({fab/len(unanswerable):.0%})  answered an unanswerable one")

    if args.judge:
        judged = [r for r in answerable if "judge" in r]
        if judged:
            m = sum(r["judge"] == "match" for r in judged)
            print("\nTier 2 (advisory -- spot-check by hand)")
            print(f"  Correct         {m}/{len(judged):<3} ({m/len(judged):.0%}) of answers given")

    print(f"\n  notional cost   ${cost:.4f}   (free tier: nothing billed)")
    print(f"  one row is worth ~{100/len(answerable):.0f} points -- small moves are noise")

    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = RESULTS / f"{args.label}-{stamp}.json"
    out.write_text(json.dumps(
        {"label": args.label, "at": stamp, "model": args.model, "prompt": args.prompt,
         "false_refusal": fr, "answerable": len(answerable),
         "fabrication": fab, "unanswerable": len(unanswerable),
         "results": results}, indent=2))
    print(f"\n  saved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
