# Decision log

Six decisions that shaped the product, with the evidence behind each. Where a
decision overturned an earlier assumption of mine, that is recorded rather than
tidied away.

---

## 1. Verify each claim against its own source, rather than trusting citations

**Decision.** After the model writes an answer, re-read the cited source and check
that it actually supports the claim. Drop anything it doesn't.

**Why.** A citation records where the model *looked*, not what the source *says*.
Those come apart routinely: the model reads a pricing page, then writes a sentence
about customer counts the page never mentions. The URL is real, the sentence is
plausible, and nothing connects them.

This is the product's reason to exist. Without it the tool is a competitor-research
demo, of which there are many.

**Cost.** Roughly $0.00017 per claim — about $0.003 to verify a 20-claim brief.
Cheap enough that the interesting question was never cost but whether accuracy
holds.

---

## 2. Fetch a fixed list of pages instead of using Google Search grounding

**Decision.** Read a curated list of URLs per company from `sources.json`, cached
to disk, rather than letting the model search the web.

**Why (initially forced).** Search grounding is not available on the Gemini free
tier. Attaching the `google_search` tool returns 429 on every model, while the same
models succeed without it — confirmed by testing both with and without, so it was
the tool and not the model.

**Why (kept deliberately).** Fixed sources make the eval trustworthy. If the system
re-searched each run, a score that moved might just be a search result that moved,
with no way to attribute it. For a project whose entire premise is trustworthy
measurement, reproducibility was worth more than discovery.

**Cost, stated honestly.** No discovery. The system only reads pages we listed, so
it will never surface a source we didn't think of. That is a real product
limitation, not a neutral trade.

---

## 3. Measure both failure directions, not just fabrication

**Decision.** Report false refusal alongside fabrication, and score refusal rows
so that confidently answering them *costs* you.

**Why.** Fabrication was 0% from the first run and never moved. Reported alone, it
reads as a solved problem — while the same system was refusing 58% of the questions
it should have answered. A one-sided metric would have called that success.

The rates trade against each other, so the threshold between them is the product
decision: a fabricated price in a board deck is severe and invisible, a missing
line is mild and visible. Lean strict, but not into uselessness.

**Result.** This is the single decision that made the rest of the work possible. It
is also why the eval could not be gamed by making the system more cautious.

---

## 4. Adopt the looser answering prompt, on measurement rather than instinct

**Decision.** Default to a prompt that answers from a clear, direct reading of a
source. Keep the stricter variant as `ANSWER_SYSTEM_STRICT` for comparison.

**Why.** The strict prompt refused any question containing a superlative — "the
primary differentiator", "announced most recently" — reasoning that no page ranks
its features or orders its announcements. Literally true. It cost two answerable
rows and bought nothing:

| | strict | default |
|---|---|---|
| Correct | 8/10 | **9/10** |
| False refusal | 20–30% | **0%** |
| Fabrication | 0% | **0%** |

Fabrication stayed at zero either way, so the strictness was pure cost. The strict
variant was also *less stable* — 2 then 3 refusals across runs.

**Kept the alternative** so the comparison is reproducible rather than a claim in a
commit message. If a later change pushes fabrication above zero, it is the fallback.

---

## 5. Run every configuration repeatedly before believing any number

**Decision.** Run each config unchanged 3–4 times and report the spread.

**Why.** On a 10-row set, one row is 10 points. The improvement I had reported was
a one-row difference with no noise floor to judge it against — literally
indistinguishable from run-to-run variance at that point.

**What it caught.** I had reported 100% correctness. Three repeats all scored 9/10.
The 100% was the lucky tail, and would have gone into this document as a quality
claim it cannot support. It also showed the *binary* answer/refuse decision is
perfectly stable while answer *completeness* wanders — a distinction invisible in a
single run.

**Result.** The claim changed from "90% → 100%" to "**90%, stable**", and became
defensible.

---

## 6. Use the cheaper model — after the evidence contradicted the design

**Decision.** `gemini-3.1-flash-lite` for the reasoning step, not a Flash-tier model.

**Why.** The architecture was built on a two-tier assumption: spend capability
where it matters, save it where it doesn't. Measurement inverted that.

| Model | $/1M in–out | False refusal | Correct |
|---|---|---|---|
| `gemini-3.1-flash-lite` | 0.25 / 1.50 | **0%** | **9/10** |
| `gemini-3.6-flash` | 0.75 / 3.75 | 20% | 7/10 |

The cheaper model is 3× less expensive **and better on both measures**. The more
capable one refused `p01` and `l02` — the same rows the strict prompt balked at,
suggesting those sit near a genuine judgement boundary.

**Confidence: moderate, not high.** 3.6-flash got one run against Flash-Lite's
four, because the free tier caps Flash-tier models at 20 requests/day and one eval
run is 17. The direction is clear; the magnitude is not established.

**The honest version of this decision** is that I designed a two-tier split on an
assumption, measured it, and found the assumption wrong. The design survived only
because the measurement was built before the conclusion.
