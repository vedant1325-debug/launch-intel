# Evaluation report

## What is measured, and why

The product requirement is **provable, not plausible**. An LLM asked to research a
competitor will write a confident sentence and attach a real URL that never said
it — and for a GTM brief that is worse than useless, because a wrong price does
not look wrong. It looks like research.

So the system is scored on whether it stays inside what its sources support, in
**both** directions:

| Metric | Tier | Definition |
|---|---|---|
| **False refusal** | 1 | Of the answerable rows, how many did it decline? |
| **Fabrication** | 1 | Of the unanswerable rows, how many did it answer? |
| **Correct** | 2 | Of the answers given, how many match the reference? |

**Tier 1 is objective.** Both metrics read a single boolean (`answered`) off a
structured response. No judgement, no model grading a model, nothing to dispute.

**Tier 2 needs judgement** and is scored by a second model. It is advisory. It was
hand-checked on 2 of 10 rows, and on one of those the human read was wrong and the
judge was right.

## Why two directions

A one-sided metric would have made this system look finished. Fabrication was
**0% from the very first run and never moved**. Reported alone, that reads as a
solved problem — while the same system was refusing more than half the questions
it should have answered.

The two rates trade against each other: tightening the prompt lowers fabrication
and raises false refusal. Choosing where to sit on that curve is the product
decision, and it is not a technical one:

- A fabricated price reaching a board deck is severe and invisible.
- A missing line is mild, and the reader can see something is absent.

So the system should lean strict — but not so strict it returns nothing. Finding
that point with numbers rather than opinion is the entire exercise.

## The test set

19 questions across 12 companies: **12 answerable**, **7 unanswerable**.

The 7 unanswerable rows ask for figures nobody publishes — churn, CAC, gross
margin, sub-team headcount. There is no right answer to find, and answering them
confidently is scored as a failure.

Sources are a fixed list of public pages per company, cached to disk. Fixed on
purpose: if the system re-searched the web each run, a score that moved might just
be a search result that moved, and there would be no way to tell which.

## Results

| Run | Model | Prompt | False refusal | Fabrication | Correct |
|---|---|---|---|---|---|
| `baseline` | flash-lite | strict | 7/12 (58%) | 0/7 | — |
| `baseline-fixed` | flash-lite | strict | 2/10 (20%) | 0/7 | 8/10 |
| `strict-repeat` | flash-lite | strict | 3/10 (30%) | 0/7 | — |
| `loose` | flash-lite | loose | 0/10 (0%) | 0/7 | 9/10 |
| `final` | flash-lite | default | 0/10 (0%) | 0/7 | 10/10 |
| `repeat1` | flash-lite | default | 0/10 (0%) | 0/7 | 9/10 |
| `repeat2` | flash-lite | default | 0/10 (0%) | 0/7 | 9/10 |
| `repeat3` | flash-lite | default | 0/10 (0%) | 0/7 | 9/10 |
| `flash-3.6` | 3.6-flash | default | 2/10 (20%) | 0/7 | 7/10 |

### Headline

**False refusal fell from 20–30% to a stable 0%, with fabrication at 0%
throughout. Answer correctness is 90%.**

### Separating the measurement from the system

The raw arc is 58% → 0% false refusal. Most of that was not the system improving:

| Change | False refusal | What actually changed |
|---|---|---|
| First measurement | 58% | — |
| Added 3 missing sources, dropped 2 malformed rows | 20% | **the eval** |
| Loosened the answering prompt | 0% | **the system** |

Only the last line is a product improvement. Quoting "58% → 0%" as an achievement
would be taking credit for fixing my own test set.

The first baseline's 7 false refusals had three distinct causes:

- **2 genuine over-strictness** (`p01`, `s01`) — `p01` had both the tier name and
  the $10 price and still refused, unable to confirm the billed-annually detail.
- **2 malformed rows** (`p05`, `f01`) — `p05` asked about a Retool "standard plan"
  that does not exist, so refusing was *correct*; `f01`'s reference answer was
  `8-K`, a filing type rather than a customer count.
- **3 missing sources** (`l01`, `l02`, `l04`) — the questions ask for announcement
  details while the listed sources were current product pages. The model was right;
  the source list was wrong.

A first baseline measures the eval at least as much as the system. That is what it
is for.

### Variance

Every configuration above 4 runs deep was run repeatedly, because a one-row
difference on a 10-row set is 10 points and means nothing without a noise floor.

- **Tier 1 is perfectly stable.** The default config returned 0/10 and 0/7 on all
  four runs — every row behaving identically every time. So the false-refusal fix
  is real, not variance.
- **Tier 2 is not.** Three repeats scored 9/10; one scored 10/10. The 100% was the
  lucky tail. `s02`'s reference answer names two target users — developers *and* AI
  coding agents — and the system mentions the second only sometimes. The judge was
  consistent; the system's answer completeness is what wanders.
- **The strict variant is unstable too**: 2/10 then 3/10, always drawn from the
  same three rows. So the adopted prompt is not merely better on average, it is
  more predictable.

**The honest correctness figure is 90%, not 100%.**

### Model comparison

| Model | $/1M in–out | False refusal | Correct | Cost/run | Runs |
|---|---|---|---|---|---|
| `gemini-3.1-flash-lite` | 0.25 / 1.50 | 0% (stable) | 9/10 | $0.032 | 4 |
| `gemini-3.6-flash` | 0.75 / 3.75 | 20% | 7/10 | $0.094 | 1 |

The cheaper model is **3× less expensive and better on both measures**. This
contradicts the assumption the architecture was built on — that capability was
worth paying for at the reasoning step. On this task it was not, and the more
capable model refused `p01` and `l02`, the same rows the strict prompt balked at.

Both models mark `s02` partial, so that row is a property of the task rather than
of either model.

## Limitations

Stated plainly, because a reader who finds these unaided will discount everything
above.

1. **The comparison is not symmetric.** 3.6-flash got one run against Flash-Lite's
   four. Its 20% has no variance behind it. The free tier caps Flash-tier models at
   20 requests/day and one eval run is 17.
2. **`gemini-3.7-flash` was the intended comparison and is unrun.** A crashed
   attempt plus quota probes exhausted its daily allowance.
3. **The set is small.** 10 answerable rows; one row is 10 points.
4. **The set is easy.** It has hit its ceiling and can no longer discriminate
   between further changes. Sources are mostly first-party pages, and companies
   state their own pricing plainly.
5. **The refusal rows are the easy kind.** "Nobody publishes churn" is trivially
   unanswerable. The harder case — a figure that *is* public but absent from the
   supplied sources — is untested, and that is where fabrication actually happens.
6. **Tier 2 is model-judged**, hand-verified on 2 of 10 rows.
7. **`s01` is mildly contaminated.** Its reference answer was rewritten from the
   source text, but the row was only revisited *because* the model disagreed with
   it. That is a soft form of teaching to the test.
8. **Third-party misattribution is untested.** The three market-reaction rows were
   dropped, so almost every source is a company describing itself.
9. **No checkpointing.** A failure at question 15 loses all 15 and the quota spent.

## What to do next

Not more features — a harder set. Specifically: questions whose answers exist
publicly but are absent from the supplied sources, and third-party sources where
misattribution is possible. The current set can no longer tell whether a change
helps.
