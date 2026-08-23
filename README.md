# Launch Intel

GTM competitive intelligence that cites its sources — and drops the claims it can't back up.

Point it at a competitor. It researches their recent launches from public web
sources and returns a go-to-market brief covering positioning, differentiators,
pricing cues, and channel mix. Every assertion carries the source it came from,
and every assertion has been checked against that source before you see it.

## The problem it solves

An LLM asked to research a competitor will write a confident sentence and staple
a plausible URL to it. The URL is usually real. The sentence is often true. But
nothing connects the two — the model is not quoting the page, it's recalling a
vibe and citing a page that looks like it would agree.

For a GTM brief this is worse than useless. A pricing figure that's off by 40%
doesn't read as wrong, it reads as research, and it ends up in a board deck.

So this project treats *provable* as the product requirement, not *plausible*:

| Stage | What happens |
|---|---|
| 1. Research | Gemini + Google Search grounding drafts a brief from public sources |
| 2. Extract | The draft is decomposed into atomic claims, each bound to one source URL |
| 3. Verify | Each claim is re-checked against its own source by a second, cheaper model |
| 4. Assemble | Unsupported claims are dropped; survivors get confidence badges |

Stage 3 is the whole point. A claim its own source doesn't support does not
reach the reader. When too little survives, the brief says *"not enough public
data on this competitor"* instead of inventing the rest.

### Why grounding annotations aren't enough

Gemini's search grounding returns `url_citation` annotations mapping spans of
text to the URLs behind them, which looks like it already does stage 3. It
doesn't, and the difference is the project.

An annotation says *"the model consulted this source while writing this span."*
It does not say *"this source supports this claim."* Those come apart
constantly: the model reads a pricing page and writes a sentence about customer
counts the page never mentions. The annotation is a useful starting point for
stage 2 — it's a first draft of claim-to-source binding — but the check itself
still has to happen.

## Two-tier model architecture

Cost control is a design decision here, not an afterthought:

| Stage | Model | Rate (in/out per 1M tokens) | Why |
|---|---|---|---|
| Synthesis | `gemini-3.1-pro-preview` | $2.00 / $12.00 | Hard reasoning, runs once |
| Verification | `gemini-3.1-flash-lite` | $0.25 / $1.50 | Easy judgement, once per claim |

Verification is where the call volume is — a 20-claim brief means 20 calls. Using
the Pro model to answer "is this sentence in this text?" would be 8x the price
for no measurable quality gain. `estimate_cost()` in `src/verify.py` tracks real
token counts so the cost/latency table is measured rather than estimated.

`gemini-3.1-pro-preview` is a preview model and may change; `gemini-3.7-flash`
($0.75 / $3.75) is the stable fallback for synthesis.

## Evals

`evals/golden_set.example.jsonl` shows the shape. Questions about companies whose
answers are independently checkable, scored on **citation accuracy** — does the
cited source actually support the claim — rather than on whether the prose reads
well.

The set deliberately includes rows where the correct behaviour is refusal. A
system that answers all 25 confidently scores *worse* than one that answers 19
and declines 6, and the eval has to reflect that or it rewards exactly the
failure mode this project exists to fix.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python src/verify.py --stub    # offline, no key, no cost -- verifies the wiring

cp .env.example .env           # add your Gemini key, then:
python src/verify.py           # the real thing
```

Get a free key from [Google AI Studio](https://aistudio.google.com/apikey). No
second data provider is needed — web search runs as a Gemini tool call, so the
Gemini key is the only credential. The free tier includes 5,000 Google Search
grounding requests per month; this project needs a few hundred.

**`--stub` tests wiring, not quality.** It substitutes crude word matching for
judgement. Never put a stub number in the eval report.

## Credit

The starting idea — agentic GTM launch intelligence with separate competitor,
sentiment, and metrics analysis — comes from the
[Product Launch Intelligence Agent](https://github.com/Shubhamsaboo/awesome-llm-apps/tree/main/advanced_ai_agents/multi_agent_apps/product_launch_intelligence_agent)
in [awesome-llm-apps](https://github.com/Shubhamsaboo/awesome-llm-apps) (Apache-2.0).

This is an independent implementation, not a fork. The architecture differs in
the ways that matter: claim-level verification, a two-tier model split, explicit
refusal, and an eval harness — none of which the original has. The original uses
OpenAI + Firecrawl; this uses Gemini with Google Search grounding.
