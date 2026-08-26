# Launch Intel — product requirements

## The problem

Product marketers and PMs building go-to-market plans need to know what a
competitor just shipped, how they position it, and what they charge. That research
is slow, and it goes stale within weeks.

The obvious fix — ask an LLM — fails in a way that is worse than being slow. Asked
to research a competitor, an LLM writes a confident, well-formatted sentence and
attaches a plausible URL. The URL is usually real. The sentence is often true. But
nothing connects the two: the model is recalling an impression and citing a page
that looks like it would agree.

**A wrong price does not look wrong. It looks like research.** It reaches a board
deck, and by the time anyone checks, a positioning decision has been made on it.

## The user

A product marketer or PM preparing competitive input for a launch decision. They
are not going to verify every line — that is the work they were trying to avoid. So
the tool has to be trustworthy without supervision, or it is worse than nothing.

The distinction that matters to them: **a gap they can see is fine; a confident
error they cannot see is not.** They can work around "no public data on this." They
cannot work around a fabricated price.

## What it does

Company name in, sourced brief out — positioning, differentiators, pricing cues,
channels. Every factual sentence carries the source it came from, and has been
checked against that source before the reader sees it.

| Stage | |
|---|---|
| 1. Research | Read a fixed list of public pages for the company |
| 2. Draft | Write the brief, tagging every sentence with its source (`[S2]`) |
| 3. Verify | Re-check each claim against the source it cites |
| 4. Assemble | Drop unsupported claims; badge the rest by confidence |

When too little survives, it says **"not stated in the sources"** rather than
filling the gap. Refusing is a feature, and it is scored as one.

## What "good" means

Measured, not asserted. Three numbers, reported together:

- **False refusal** — declined something the sources do state
- **Fabrication** — answered something they don't
- **Correctness** — of answers given, how many are right

Fabrication alone is not enough. A system that refuses everything scores 0%
fabrication and is useless. Both directions or neither.

Current: **0% false refusal (stable over 4 runs), 0% fabrication, 90% correct.**
Full methodology, variance and limitations in [EVAL_REPORT.md](EVAL_REPORT.md).

## Deliberately not built

Each of these was considered and cut. The project is judged on whether its claims
are true, and none of these move that.

| Cut | Why |
|---|---|
| **Multiple competitors per run** | Nothing learned that one competitor doesn't teach |
| **Source discovery** | Fixed sources make the eval reproducible. Real cost, taken knowingly — see [DECISIONS.md](DECISIONS.md) #2 |
| **Sentiment and metrics agents** | The competitor path had to be trustworthy first |
| **Auth, accounts, saved history** | No bearing on claim accuracy |
| **PDF export** | Presentation, not substance |
| **A second LLM provider** | Portability is not the problem being solved |

## Known limitations

The honest list, not a reassuring one:

- **Reads only listed pages.** No discovery — miss a source and the tool doesn't
  know it exists.
- **The eval has hit its ceiling.** 10 answerable rows scoring 90–100%; it can no
  longer tell whether the next change helps.
- **Third-party misattribution is untested.** Nearly every source is a company
  describing itself, which is the favourable case.
- **Correctness is model-judged**, hand-verified on 2 of 10 rows.
- **Free-tier quota caps iteration** at roughly one eval run per day on any
  Flash-tier model.
- **Answer completeness wavers** run to run, even where the answer/refuse decision
  is stable.

## What I'd do next

**Make the test harder, not the product bigger.** Specifically: questions whose
answers exist publicly but are absent from the supplied sources — that is where
fabrication actually happens, and it is currently untested. Then third-party
sources, where a citation can point at a real page that doesn't support the claim.

Only once the eval discriminates again is there any point adding features, because
until then there is no way to know if they helped.
