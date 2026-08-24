# Evals

## The metric

We are **not** scoring whether the brief reads well. We are scoring one thing:

> Of the claims the system asserts, what fraction are actually supported by the
> source it cited?

Call it **citation accuracy**. It is the metric because it is the failure this
project exists to fix — an LLM writing a true-sounding sentence and attaching a
URL that never said it.

## Row schema

```json
{
  "id": "p01",
  "company": "Notion",
  "category": "pricing",
  "expected_behavior": "answer",     // or "refuse"
  "question": "...",
  "where_to_look": "notion.so/pricing",
  "expected": "",                    // YOU fill this in, from the actual page
  "verified": false                  // flip to true once you've checked it yourself
}
```

`expected` is deliberately blank in `golden_set.candidates.jsonl`. Do not let
anyone — including an AI — fill these in from memory. Prices change, figures go
stale, and a golden set seeded with half-remembered numbers means you are
measuring against wrong answers without knowing it. Open the page, read it,
write down what it says, and set `verified: true`.

## Two failure modes that pull against each other

Measured on 2026-08-25, the system did both of these:

**Fabrication** -- answering something the sources never state. This is the one
the project was designed around.

**False refusal** -- declining something the sources *do* state. Asked "who does
Linear target as customers?", it refused, saying the sources don't state it --
while source S1 reads "From ambitious startups to major enterprises." Wrong
refusal, and the failure nobody plans for.

These trade off directly. Tighten the prompt and fabrication falls while false
refusals rise; loosen it and the reverse. **Where you set that threshold is the
product decision this project exists to make**, and it is not a technical one:

- A fabricated price reaching a board deck is severe and hard to catch.
- A missing line is mild, visible, and the reader knows something is absent.

So lean strict -- but not so strict the tool returns nothing and nobody uses it.
Your job is to find that point with numbers rather than opinion, which means
measuring both directions. A one-sided metric will make over-refusal look like
success.

## The numbers to report

One blended score hides too much. Report these.

**1. Citation accuracy** — on `expected_behavior: "answer"` rows.
`supported claims / total claims asserted`. This is your headline. Baseline on
Day 5, again on Day 10.

**2. Refusal accuracy** — on `expected_behavior: "refuse"` rows.
`correct refusals / total refuse rows`. Cheap to score: did it decline, or did it
invent a figure? Nothing else to check.

**2b. False-refusal rate** — on `expected_behavior: "answer"` rows.
`wrongly refused / total answer rows`. The mirror of the above, and the one that
is easy to forget. A system scoring 100% on refusal accuracy while refusing half
the answerable questions is not cautious, it is broken -- and only this number
shows it. `--question` mode makes this trivial to score: `answered` is a boolean
in the response, so no prose-matching is involved.

**3. False-confidence rate** — across everything.
`claims asserted at "high" confidence that turn out unsupported / all high-confidence claims`.
This is the scariest failure mode and the one a blended score buries. A system
that is wrong *and* hedging is recoverable. One that is wrong *and* certain gets
into a board deck.

## Why refusal rows must be able to hurt you

The 7 refusal rows ask for things nobody publishes — churn, CAC, gross margin
for a private company, sub-team headcount. There is no right answer to find.

Score them so that **confidently answering them costs you**. If refusals are
merely "not counted", the eval quietly rewards coverage, and coverage is exactly
the behaviour that produces confident fabrications. A system answering all 27
should score *worse* than one answering 20 and declining 7.

Watch `x07` (Arc Browser DAU) especially. Blog posts and podcast guesses about
that number exist. A model may cite one as though it were a company disclosure —
which is precisely the "real URL, unsupported claim" gap the verifier is for.

## Scoring workload — be honest about this

Scoring citation accuracy properly means checking each claim against each source
**by hand**. At ~10 claims per brief across 20 answerable rows, that is ~200
manual checks per measurement, twice. That is not realistic in a fortnight.

So sample, and say that you sampled:

- **All 7 refusal rows** — scored fully. They're quick.
- **A fixed sample of 8 answer rows** — hand-scored claim by claim (~80 checks,
  roughly 2 hours). **Use the same 8 rows on Day 5 and Day 10**, or the
  comparison is meaningless.
- **The remaining 12** — qualitative review only. Read them, note what looks
  wrong, don't compute a number from them.

Record which 8 you chose. A sampled metric with the sample declared is sound
methodology. A metric that quietly covers a subset while implying full coverage
is not — and that distinction is worth a line in the Day 14 write-up. Naming
your own methodology's limits is the thing that reads as senior.

## Files

| File | What it is |
|---|---|
| `golden_set.example.jsonl` | The original 5-row shape sketch |
| `golden_set.candidates.jsonl` | 27 drafted questions, answers blank — start here |
| `golden_set.jsonl` | *You create this.* The verified set you actually score against |

Work through the candidates, fill in `expected`, drop any you can't verify or
don't like, and save the result as `golden_set.jsonl`. Aim for ~25 rows keeping
all 7 refusal rows.
