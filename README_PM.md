# Launch Intel — Technical Product Brief

**A competitive intelligence tool that can prove what it says, and admits when it can't.**

| | |
|---|---|
| **Domain** | Go-to-market / competitive intelligence |
| **Stack** | Python, Gemini API, Streamlit |
| **Scale** | ~1,400 lines across 6 modules |
| **Measured** | 0% fabrication, 0% false refusal (stable over 4 runs), 90% answer correctness, ~$0.01 per brief |

---

## 1. Executive Summary

### The problem

Product marketers preparing a launch need to know what a competitor shipped, how they position it, and what they charge. The research is slow and stale within weeks — so the obvious move is to ask an LLM.

That fails in a way that is worse than being slow. Asked to research a competitor, an LLM writes a confident, well-formatted sentence and attaches a plausible URL. The URL is usually real. The sentence is often true. **But nothing connects the two** — the model is recalling an impression and citing a page that looks like it would agree.

The commercial danger is specific: **a wrong price does not look wrong. It looks like research.** It carries the same confident tone and tidy formatting as a correct one. It reaches a board deck, and a positioning decision gets made on it before anyone checks.

### The solution

Launch Intel treats *provable* rather than *plausible* as the product requirement.

The system drafts a brief from a fixed set of public sources, then **goes back and re-reads each cited source to confirm it actually supports the claim.** Anything that fails is dropped before the reader sees it. When too little survives, the tool says *"not enough verifiable public data"* instead of presenting fragments as a briefing.

### Why this is the right requirement

The insight driving the design is about which errors a user can absorb:

- **A gap you can see is workable.** "No public data on this" tells the reader to go look elsewhere.
- **A confident error you cannot see is not.** There is no signal to act on.

So the product optimises for *never asserting the unverifiable*, and accepts a shorter brief as the price. That is a product judgement, not a technical constraint — and it is the decision the entire architecture serves.

---

## 2. Product Architecture

Plain-English data flow:

```
INPUT      A company name  ("Linear")
             │
STAGE 1    READ SOURCES        →  a fixed list of that company's public pages,
           research.py            downloaded and cached to disk
             │
STAGE 2    DRAFT THE BRIEF     →  prose where every factual sentence carries
           research.py            the tag of the source it came from  [S2]
             │
STAGE 3    VERIFY EACH CLAIM   →  each tagged sentence is re-checked against
           pipeline.py            the source it cites, one call per claim
           verify.py
             │
STAGE 4    ASSEMBLE            →  unsupported claims dropped, survivors badged
           pipeline.py            by confidence, thin briefs flagged as thin
             │
OUTPUT     A brief where every line has a source behind it, plus a visible
           list of what was thrown away and why
```

### Two design choices worth explaining

**Sources are a fixed list, not a web search.** The system reads pages named in `sources.json` rather than searching. This began as a constraint — search grounding is not on the Gemini free tier — but was kept deliberately: **if the tool re-searched every run, a change in output might just be a change in search results.** Fixed sources mean a difference in quality is attributable to the product. For a tool whose premise is trustworthy measurement, reproducibility beat discovery.

**Stage 3 is a separate pass, not a stricter prompt.** Asking the model to "only say true things" is asking the same judgement that produced the error to also catch it. Verification is a *second* call, on a *different* model, given *one* claim and *one* source — a narrow task with no room to drift.

### A parallel path for measurement

A **question mode** answers a single question from the sources or refuses outright. This exists so quality can be scored: it returns a structured boolean, making "did it refuse?" machine-checkable rather than a matter of reading prose.

---

## 3. Core Features & Technical Implementation

### Feature 1 — Claim-level verification

**The why.** This is the product. Without it, this is one of many competitor-research demos. Verification is what converts *plausible output* into *defensible output* — and it costs about **$0.003 per brief**, which is what makes the whole premise commercially viable rather than an interesting idea.

**The code.** Verification returns a *typed verdict*, not prose:

```python
class Verdict(BaseModel):
    status: Literal["supported", "contradicted", "not_found"]
    confidence: Literal["high", "medium", "low"]
    evidence: str = Field(
        description="Verbatim sentence from the source that settles it. Empty if none."
    )
    reasoning: str = Field(description="One sentence explaining the verdict.")
```

**In plain terms:** the model is forced to answer in exactly this shape. It cannot hedge into a paragraph — it must pick one of three statuses and quote the sentence that justifies it. Because `status` is a fixed set of three values, downstream code can act on it mechanically instead of interpreting language.

Note that the `description=` text is not documentation for developers — **it is sent to the model** as part of the schema. "Empty if none" is an instruction, and it is why the field comes back blank on a refusal instead of filled with a hedge.

Assembly then applies a simple rule:

```python
@property
def kept(self) -> bool:
    """Headings pass through as structure. Prose must earn its place."""
    if self.is_heading:
        return True
    return self.verdict is not None and self.verdict.status == "supported"
```

**In plain terms:** a sentence appears in the final brief only if its own source was confirmed to support it. `verdict is None` covers sentences the model wrote without citing anything — those are dropped too, because there is nothing to check them against, and keeping them would mean asserting something on the model's word alone.

---

### Feature 2 — Refusal as a first-class, measurable outcome

**The why.** Most AI tools treat "I don't know" as a failure to be minimised. Here it is a **feature the product is scored on.** A GTM brief that admits a gap is useful; one that invents a figure is a liability. But refusal only becomes manageable if it is *measurable*, and that requires it to be structured rather than phrased.

**The code.**

```python
class SourcedAnswer(BaseModel):
    answered: bool = Field(
        description="True only if the sources actually state the answer."
    )
    answer: str = Field(
        description="The answer, one or two sentences. Empty string if answered is false."
    )
    source_ids: list[str] = Field(
        description="Source ids supporting the answer, e.g. ['S2']. Empty if not answered."
    )
    reasoning: str = Field(description="One sentence: why answered, or why not.")
```

**In plain terms:** `answered` is a **true/false flag, not a sentence.** This is the single most important line in the codebase for evaluation. Without it, scoring "did the system refuse?" would mean searching output text for phrases like *"not stated"* — which silently miscounts every time the model rephrases a refusal. One boolean makes the behaviour countable.

The product also surfaces this to the user rather than hiding it:

```python
@property
def too_thin(self) -> bool:
    """Whether to tell the reader the brief is not worth relying on.

    Saying "not enough public data" is a feature. A brief where half the
    claims failed verification should say so rather than presenting the
    survivors as though they were the whole picture.
    """
    return len(self.kept) < 3 or self.survival < 0.5
```

**In plain terms:** if fewer than three claims survived, or under half of them, the UI leads with a warning instead of presenting the remnants as a briefing. **Silently returning a thin brief would be the same failure in a different costume** — the reader would still over-trust it.

---

### Feature 3 — Two-sided evaluation

**The why.** This decision is what makes the numbers trustworthy, and it nearly went the other way.

Fabrication was **0% from the very first run and never moved.** Reported on its own, that reads as a solved problem. Measured properly, the same system was **refusing 58% of the questions it should have answered** — useless in the opposite direction, and completely invisible to a one-sided metric.

**The code.**

```python
should_answer = row["expected_behavior"] == "answer"
# The two Tier 1 failures. Both are pure booleans -- no judgement.
false_refusal = should_answer and not ans.answered
fabrication = (not should_answer) and ans.answered
```

**In plain terms:** four lines that catch both ways of being wrong. The test set contains questions with **no public answer** (churn rate, CAC, gross margin) alongside answerable ones. Answering an unanswerable question is scored as a failure — so the eval **cannot be gamed by making the system more cautious**, because caution shows up immediately as false refusal.

That property is what makes every other number in this project defensible.

---

## 4. Prompt Engineering Strategy

Four techniques, each solving a specific failure.

### Narrowing the task to remove room for drift

```
You are not judging whether the claim is true in general. You are judging one
narrow thing: does THIS text support THIS claim?
```

The verifier's failure mode is answering from world knowledge — the model *knows* what a company charges and confirms a claim without reading the source. Naming the wrong question explicitly, and rejecting it, is more effective than adding warnings.

### Making refusal socially acceptable to the model

```
`not_found` is the correct and expected answer much of the time. Reach for it
freely. A claim that is probably true but absent from this text is not_found,
never supported. Do not fill gaps with what you already know about the company.
```

Models are trained to be helpful, which biases them toward producing an answer. Stating that refusal is *expected and frequent* counteracts that pull far better than instructing them to "be careful."

### Enumerating the traps rather than stating a principle

```
Still refuse when answering would mean inventing:
- A figure no source gives, even one you could estimate from what they do give
- A generalisation drawn from examples (customer logos are not a statement about
  who the company targets)
- Something stated about one product or tier, applied to another
- A ranking or ordering across sources that give you no basis to compare
```

Each bullet is a **real failure observed during testing**, not a hypothetical. The customer-logos line exists because the system inferred a target market from a wall of logos. Concrete traps outperform abstract instructions.

### Context management: labelling, capping, and never truncating silently

Sources are injected as labelled blocks so claims can be bound to origins:

```python
blocks = "\n\n".join(
    f'<source id="{s.id}" url="{s.url}" title="{s.title}">\n{s.text}\n</source>'
    for s in usable
)
```

Each is capped at `MAX_CHARS = 20_000` — past that a marketing page is mostly navigation and footer. **Crucially, truncation is always recorded on the source object and shown in the UI.** A brief built on a cut-off page says so. Silent truncation would let the model appear to have read something it never saw.

The brief prompt then enforces attribution at the sentence level:

```
- End every factual sentence with the tag of the source it came from, like [S2].
- Never write a tag for a source that does not actually state the fact. An
  untagged sentence is far better than a wrongly tagged one.
- A short brief on solid sources is correct output. Do not pad a thin section.
```

Compliance measured at **100% of prose sentences tagged.**

### Constraining shape through schema, not instruction

Every structured call passes a JSON schema derived from a Pydantic model rather than asking for JSON in prose. Malformed output raises an exception at parse time instead of degrading quietly — a wrong answer that *looks* fine is the exact failure this product exists to prevent, so the plumbing is built to fail loudly.

**One further practice worth noting:** the rejected stricter prompt is retained in the codebase as `ANSWER_SYSTEM_STRICT`. The comparison that justified the current default stays reproducible, rather than surviving only as a claim in a commit message.

---

## 5. Challenges & Trade-offs

### Trade-off 1 — Caution versus coverage (the central product decision)

The two failure modes pull directly against each other. Tightening the prompt lowers fabrication and raises false refusal.

The first prompt was tuned strict, and refused any question containing a superlative — *"the primary differentiator"*, *"announced most recently"* — reasoning that no page ranks its features or orders its announcements. **Literally true, and it cost real coverage:**

| | Strict | Adopted |
|---|---|---|
| Answer correctness | 8/10 (80%) | **9/10 (90%)** |
| False refusal | 20–30% | **0%, stable over 4 runs** |
| Fabrication | 0% | **0%** |

**Fabrication stayed at zero either way**, so the strictness was buying no safety — only cost. The strict variant was also *less stable*, refusing 2 rows then 3 across identical runs.

**How the trade-off was resolved:** by measuring both directions, not by picking a philosophy. The asymmetry of harm sets the direction — a fabricated price in a board deck is severe and invisible; a missing line is mild and visible — so the system should lean cautious. But *how far* is an empirical question, and the data said the strict setting had overshot.

### Trade-off 2 — Reproducibility versus discovery

Reading a fixed source list means **the system can never surface a source you didn't think to include.** That is a genuine product limitation, and it is stated in the user-facing docs rather than hidden.

It was accepted because the alternative is worse for this product's purpose. With live search, the source set changes every run, so a difference in output cannot be attributed to a change in the product. For a tool whose entire claim is *trustworthy measurement*, an unmeasurable improvement is not an improvement.

### Handling edge cases: the silent-failure class

Two bugs found in testing shared a shape worth naming, because it is the dangerous one in a sourcing product:

- **PDFs** were decoded as text, producing ~11,000 characters of binary noise. The fetch reported **success**.
- **JavaScript-only sites** returned a 10-character empty shell. Also **HTTP 200, no error**.

In both cases the model received garbage as an authoritative source and would either refuse everything or invent an answer — with nothing anywhere in the system indicating a problem.

Both are now handled: PDFs extract via `pypdf`, and a printable-character ratio check rejects other binary content. The generalisable lesson: **in a system whose value is source fidelity, a fetch that succeeds while returning nothing usable is more dangerous than one that crashes.** Every source-loading path now fails loudly or records why.

### An assumption that measurement overturned

The architecture was built on a two-tier premise — spend capability where reasoning is hard, save it where the task is mechanical. Testing inverted it:

| Model | $/1M tokens | False refusal | Correct |
|---|---|---|---|
| `gemini-3.1-flash-lite` | 0.25 / 1.50 | **0%** | **9/10** |
| `gemini-3.6-flash` | 0.75 / 3.75 | 20% | 7/10 |

The cheaper model is **3× less expensive and better on both measures.** The design survived only because the measurement existed before the conclusion. *(Confidence: moderate — the expensive model got one run against four, as free-tier quota caps Flash-tier models at 20 requests/day.)*

---

## 6. Future Roadmap

### 1. An adversarial evaluation set

**Why now:** the current set is exhausted. At 90–100% it can no longer tell whether a change helps or hurts, which means further development would be guesswork.

The specific gap: every question is either answerable from the supplied sources or answerable from nowhere. **The untested case — and where fabrication actually happens — is a question whose answer exists publicly but is absent from the sources provided.** That is precisely the situation where a model is tempted to reach for what it knows.

Adding third-party sources (press, forums) alongside adversarial rows would restore the set's ability to discriminate. **This should ship before any new feature**, because until the eval works again there is no way to know whether a feature helped.

### 2. Source discovery with frozen snapshots

**Why now:** this recovers the one real capability the architecture gave up, without surrendering what was gained.

The design: run discovery **once** per company to propose candidate sources, then **freeze that list and cache the page contents.** Discovery becomes a setup step rather than part of every run. The user gets sources they wouldn't have found; the eval keeps a fixed corpus, so a score change remains attributable to the product.

This resolves the reproducibility-versus-discovery trade-off rather than merely choosing a side — which is why it belongs on the roadmap instead of being a reversal of Trade-off 2.

---

## Appendix — Supporting documentation

| Document | Contents |
|---|---|
| [`docs/EVAL_REPORT.md`](docs/EVAL_REPORT.md) | Full methodology, all 9 recorded runs, per-run variance, model comparison, 9 stated limitations |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | 6 decisions with supporting evidence, including 2 where measurement overturned the original assumption |
| [`docs/PRD.md`](docs/PRD.md) | Problem framing, user definition, explicit scope cuts |
| [`evals/README.md`](evals/README.md) | Metric definitions and the sampling policy |

**One caveat stated plainly**, because a reader who finds it unaided discounts everything above it: the headline arc is 58% → 0% false refusal, but **only about a third of that improvement was the system.** The remainder was correcting flaws in the test set itself — three missing sources and two malformed questions. `docs/EVAL_REPORT.md` separates the two, because conflating them would mean taking credit for fixing my own measurement.
