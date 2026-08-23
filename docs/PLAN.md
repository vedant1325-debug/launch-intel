# Two-week build plan

Goal: a working product **and** the artifacts that prove product judgement.
For an AI PM role the second half is what gets you hired, so it is scheduled
work, not something to write up at the end if there's time.

## Guiding rule

Build the eval harness in week 1, before the quality work. You cannot claim you
improved anything without a baseline number, and "I added verification and
accuracy went from 61% to 89%" is the single most valuable sentence in the whole
project. That sentence is only available if you measured *first*.

## Billing

Gemini's free tier covers the models we need, and Google Search grounding
includes 5,000 free requests per month (then $14/1,000). This project needs a few
hundred. **Realistic expectation: $0**, or a few dollars if free-tier rate limits
push you to paid.

If you do go paid: `gemini-3.1-pro-preview` is $2.00/$12.00 per 1M tokens in/out,
`gemini-3.1-flash-lite` is $0.25/$1.50. That 8x gap is the basis of the Day 12
table. Get your own key from Google AI Studio rather than borrowing one — a key
that gets rotated mid-project stalls you, and a portfolio piece shouldn't depend
on credentials you don't control.

Cache sources to disk regardless of cost. Free tiers have rate limits, and more
importantly: if you re-search the web on every eval run, a score that moves might
just be a search result that moved, and you can't tell which. Caching is about
trustworthy measurement, not only money.

---

## Week 1 — make it work, and measure how badly

**Day 1 — Setup and first contact.**
Create the virtualenv, install `requirements.txt`. Run `python src/verify.py --stub`
(free, no key) to confirm the plumbing. Then put a Gemini key in `.env` and run
`python src/verify.py` for real.
*Success check:* two verdicts print — claim 1 `supported`, claim 2 `not_found`.
If claim 2 comes back `supported`, the model is leaning on world knowledge
instead of reading the source. That's your first real bug, and it's the exact
failure this project exists to catch.

**Day 2 — First brief, and source caching.**
Write `src/research.py`: company name in, `tools=[{"type": "google_search"}]` on,
draft brief out. **Save every source page to `runs/<company>/` as you go, plus
the `url_citation` annotations** — you need those on Day 6.
*Success check:* a real brief about a real company prints; `runs/` has files.

**Days 3-4 — The test set. No code at all.**
Expand `evals/golden_set.example.jsonl` from 5 rows to ~25. Pick companies you
can independently verify: public pricing pages, real filings, launches you
remember. Look up each answer yourself in a browser.

**Include 5-6 rows where the right answer is "no reliable public data."** These
are the most important rows, not filler. A system that confidently answers all
25 should score *worse* than one answering 19 and declining 6.

Highest-value work of the fortnight, and zero programming. Also the part most
people skip — which is exactly why doing it makes you stand out.

**Day 5 — Baseline.**
Write `src/run_evals.py`: loop the 25 questions through the current unverified
pipeline and count how many claims are genuinely supported by the source cited.
Write the number down. Expect 55-70%.
**Fix nothing today.** Resisting that is the whole point.

**Days 6-7 — Claim extraction.**
Write `src/extract.py`. Start from the `url_citation` annotations — Gemini gives
you a rough claim-to-source binding for free — then clean them into atomic
standalone claims with a Pydantic model.

Expect several rounds. Annotated spans are not clean claims: they overlap, some
cover half a sentence, some cover filler with nothing checkable in it, and some
claims need the previous sentence to make sense. You're editing a rough draft
rather than starting blank, but it still takes iteration.
*Success check:* feed in a brief you know well; the claims list looks
hand-checkable.

**Day 8 — Buffer.**
Freed up by the annotations doing part of Day 6's work. Use it to catch up or to
strengthen the test set. Do **not** start new features.

---

## Week 2 — make it honest, and write it up

**Days 9-10 — Wire in the verifier, then re-measure.**
`src/verify.py` already implements stage 3. Connect extraction to it, run every
claim through, drop what doesn't survive. Re-score against the golden set.
**This is the payoff.** The gap between this number and Day 5's is your headline
result. Record both carefully.

**Day 11 — Refusal and confidence.**
Add the thin-evidence path: when too few claims survive for a section, say so
instead of padding. Surface the confidence badges. Verify the golden set's
refusal rows now behave correctly — much of your remaining score lives here.

**Day 12 — Cost and latency table.**
Real numbers from `estimate_cost()`, not estimates. Per-brief cost, p50 latency,
and the counterfactual: run verification once with `gemini-3.1-flash-lite` and
once with `gemini-3.1-pro-preview`, and show the accuracy difference is
negligible while the price gap is 8x.

That table *is* the argument for the two-tier architecture. Without it you made a
choice; with it you justified one.

**Day 13 — Streamlit UI.**
Only now. One input, one brief, badges and sources visible. ~20 lines. Resist
features.

**Day 14 — The PM artifacts.**
- **PRD** (2 pages): the user, the job, what you deliberately cut and why.
- **Eval report**: baseline vs verified, the metric definition, what still fails.
- **Decision log**: 4-5 real tradeoffs with reasoning. Cheap model for checking.
  Refusal over coverage. Claim-level over document-level verification. Why
  grounding annotations aren't sufficient on their own.
- **Known limitations**, written honestly. Interviewers probe here, and a
  candidate who already knows the weak spots reads as senior. One who claims
  none reads as junior.

Then make the repo public.

---

## Scope discipline

Things that will tempt you and should be cut:

- More than one competitor at a time
- Auth, accounts, saved history
- The sentiment and metrics agents — land the competitor-analysis path first
- PDF export
- A second LLM provider

The project is judged on whether the claims it makes are true and whether you can
explain your decisions. Nothing on that list moves either.

## What "done" looks like

A brief you'd be willing to hand a real GTM team, where every line is backed and
the gaps are labelled as gaps — plus a measured before/after table and a PRD
explaining the calls you made. That is a portfolio piece. A prettier app with
unverified claims is not.
