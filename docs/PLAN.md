# Two-week build plan

Goal: a working product **and** the artifacts that prove product judgement.
For an AI PM role the second half is what gets you hired, so it is scheduled
work, not something to write up at the end if there's time.

## Guiding rule

Build the eval harness in week 1, before the quality work. You cannot claim you
improved anything without a baseline number, and "I added verification and
accuracy went from 61% to 89%" is the single most valuable sentence in the whole
project. That sentence is only available if you measured *first*.

---

## Week 1 — make it work, and measure how badly

**Days 1-2 — the spine.**
Get one competitor end-to-end: query in, draft brief out, using Claude with the
`web_search_20260209` server tool. Ugly output is fine. Streamlit can wait; a
script that prints to the terminal is the right scope. The only goal is a real
brief from real sources.

**Day 3 — the golden set.**
Expand `evals/golden_set.example.jsonl` from 5 rows to ~25. Pick companies you
can independently verify: public pricing pages, real filings, launches you
remember. Include 5-6 rows where the right answer is **refusal** — no reliable
public data exists. Those rows are the point of the set, not filler.

**Day 4 — baseline.**
Score the naive pipeline against the golden set. Metric: of the claims it makes,
what fraction are actually supported by the source cited? Expect something
between 55% and 70%. Write the number down. Resist the urge to fix anything
today.

**Days 5-7 — claim extraction.**
Stage 2: decompose a draft brief into atomic claims each bound to one source URL,
using structured outputs (`client.messages.parse` with a Pydantic model). This is
fiddly — one sentence often carries two claims, and vague sentences carry none.
Getting the decomposition right is most of the work in this project.

---

## Week 2 — make it honest, and write it up

**Days 8-9 — wire in the verifier.**
`src/verify.py` already implements stage 3. Connect extraction to it, run every
claim through, and drop what doesn't survive. Then re-score against the golden
set. This is the payoff moment: the delta between this number and day 4's is
your headline result.

**Day 10 — refusal and confidence.**
Add the thin-evidence path: when too few claims survive for a section, say so
instead of padding. Surface the confidence badges. Verify the golden set's
refusal rows now behave correctly — this is where most of the remaining eval
score lives.

**Day 11 — cost and latency table.**
Real numbers from `estimate_cost()`, not estimates. Per-brief cost, p50 latency,
and the counterfactual: what an all-Opus pipeline would have cost. Then run the
verifier once on Opus and once on Haiku across the golden set and show the
accuracy difference is negligible. That table *is* the argument for the two-tier
architecture — without it you just made a choice, with it you justified one.

**Day 12 — Streamlit UI.**
Only now. One input, one brief, badges and sources visible. Resist features.

**Days 13-14 — the PM artifacts.**
- **PRD** (2 pages): the user, the job, what you deliberately cut and why.
- **Eval report**: baseline vs. verified, the metric definition, and what still fails.
- **Decision log**: 4-5 real tradeoffs with the reasoning. Two-tier models.
  Refusal over coverage. Claim-level over document-level citation. Dropping
  Firecrawl for server-side web tools.
- **Known limitations**: written honestly. Interviewers probe here, and a
  candidate who already knows the weak spots reads as senior. A candidate who
  claims none reads as junior.

---

## Scope discipline

Things that will tempt you and should be cut:

- More than one competitor at a time
- Auth, accounts, saved history
- The sentiment and metrics agents — land the competitor-analysis path first
- PDF export
- Any second LLM provider

The project is judged on whether the claims it makes are true and whether you can
explain your decisions. Nothing on that list moves either.

## What "done" looks like

A brief you'd be willing to hand a real GTM team, where every line is backed and
the gaps are labelled as gaps — plus a measured before/after table and a PRD
explaining the calls you made. That is a portfolio piece. A prettier app with
unverified claims is not.
