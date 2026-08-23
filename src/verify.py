"""
Claim verifier -- the core of Launch Intel.

Stage 3 of the pipeline. Takes the atomic claims pulled out of a draft brief and
checks each one against the source it cites. Anything the source does not
actually support gets dropped or flagged, so the finished brief only asserts
what it can back up.

Why this module exists: an LLM asked to research a competitor will happily write
a confident sentence and staple a plausible URL to it. The URL is usually real
and the sentence is often true -- but nothing guarantees the URL is where the
sentence came from. This module is that guarantee.

A note on Gemini's grounding annotations, since they look like they do this job
and don't: a `url_citation` says "the model consulted this source while writing
this span". It does not say "this source supports this claim". Those come apart
constantly -- the model reads a pricing page, then writes a sentence about
customer counts the page never mentions. Closing that gap is this module's job.

Model choice is deliberate and is the project's main cost lever:

    stage 1, synthesis     -> gemini-3.1-pro-preview   hard reasoning, low volume
    stage 3, verification  -> gemini-3.1-flash-lite    easy judgement, high volume

Verification runs once per claim, so a 20-claim brief is 20 calls. Paying Pro
rates to answer "is this sentence supported by this text?" is waste. Flash-Lite
is 8x cheaper on both input and output and is entirely capable of the call.
Proving that claim with numbers is the Day 12 deliverable.
"""

from dataclasses import dataclass
from typing import Literal

from google import genai
from pydantic import BaseModel, Field

# Per-million-token pricing, used by estimate_cost() for the Day 12 cost table.
# Source: ai.google.dev/gemini-api/docs/pricing (checked 2026-08-23).
# Pro input/output rises above a 200k-token prompt; we stay well under that.
PRICING = {
    "gemini-3.1-pro-preview": {"input": 2.00, "output": 12.00},
    "gemini-3.7-flash": {"input": 0.75, "output": 3.75},  # intro rate to 2026-12-31
    "gemini-3.1-flash-lite": {"input": 0.25, "output": 1.50},
}

# gemini-3.1-pro-preview is a *preview* model and can change or be withdrawn.
# If it starts misbehaving, gemini-3.7-flash is the stable fallback here.
SYNTHESIS_MODEL = "gemini-3.1-pro-preview"
VERIFIER_MODEL = "gemini-3.1-flash-lite"


@dataclass
class TokenUsage:
    """Normalised token counts.

    Both the real client and the offline stub produce one of these, so
    estimate_cost() and the eval runner don't care which one ran.
    """

    input_tokens: int
    output_tokens: int


class Claim(BaseModel):
    """One atomic, checkable assertion lifted out of a draft brief."""

    text: str = Field(description="The assertion, as a single standalone sentence.")
    source_url: str = Field(description="The URL the brief credits for this assertion.")


class Verdict(BaseModel):
    """The verifier's judgement on a single claim."""

    status: Literal["supported", "contradicted", "not_found"]
    confidence: Literal["high", "medium", "low"]
    evidence: str = Field(
        description="Verbatim sentence from the source that settles it. Empty if none."
    )
    reasoning: str = Field(description="One sentence explaining the verdict.")


VERIFIER_SYSTEM = """\
You check whether a claim is supported by a source document.

You are not judging whether the claim is true in general. You are judging one
narrow thing: does THIS text support THIS claim?

- supported    -- the text states or directly implies the claim
- contradicted -- the text states something incompatible with the claim
- not_found    -- the text simply does not address the claim

`not_found` is the correct and expected answer much of the time. Reach for it
freely. A claim that is probably true but absent from this text is not_found,
never supported. Do not fill gaps with what you already know about the company.

Set confidence on how cleanly the text settles the question, not on how
plausible the claim sounds.

Quote evidence verbatim from the source. Never paraphrase it, and never invent
it -- leave it empty when the status is not_found."""


def build_prompt(claim: Claim, source_text: str) -> str:
    """The verifier's input. Kept separate so the stub can parse it back apart."""
    return (
        f"<claim>\n{claim.text}\n</claim>\n\n"
        f'<source url="{claim.source_url}">\n{source_text}\n</source>\n\n'
        "Does the source support the claim?"
    )


def verify_claim(
    client,
    claim: Claim,
    source_text: str,
    model: str = VERIFIER_MODEL,
) -> tuple[Verdict, TokenUsage]:
    """Check one claim against the text of the source it cites.

    `client` is duck-typed on purpose: pass a real `genai.Client()` or the
    offline `StubClient` from stubs.py. Nothing else changes.

    The caller supplies `source_text` rather than this function fetching it.
    That keeps it trivially testable and lets the eval harness replay fixed
    sources from disk instead of re-searching the web -- which matters both for
    cost and because a moving web makes a moving eval score you can't attribute.

    Returns the verdict plus token counts, because the Day 12 cost table is a
    deliverable and needs real numbers rather than estimates.
    """
    interaction = client.interactions.create(
        model=model,
        system_instruction=VERIFIER_SYSTEM,
        input=build_prompt(claim, source_text),
        # Declaring the schema forces valid JSON in the shape of Verdict, so we
        # never hand-parse prose. If the model returns something malformed,
        # model_validate_json raises here rather than silently degrading.
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": Verdict.model_json_schema(),
        },
    )

    verdict = Verdict.model_validate_json(interaction.output_text)
    usage = TokenUsage(
        input_tokens=interaction.usage.total_input_tokens,
        output_tokens=interaction.usage.total_output_tokens,
    )
    return verdict, usage


def estimate_cost(model: str, usage: TokenUsage) -> float:
    """Dollar cost of a single call. Summed across a run to fill the cost table."""
    rates = PRICING[model]
    return (
        usage.input_tokens / 1_000_000 * rates["input"]
        + usage.output_tokens / 1_000_000 * rates["output"]
    )


def render_claim(claim: Claim, verdict: Verdict) -> str | None:
    """Turn a verified claim into a line of the final brief.

    Returns None for anything we refuse to assert. Dropping a claim is a
    feature, not a failure -- a brief of six backed claims beats one of twenty
    where four are invented, and it is the behaviour the evals reward.
    """
    if verdict.status != "supported":
        return None

    badge = {"high": "", "medium": " [medium confidence]", "low": " [thin evidence]"}
    return f"- {claim.text}{badge[verdict.confidence]}\n  source: {claim.source_url}"


if __name__ == "__main__":
    # Smoke test. Two claims against the same short source: the first is stated
    # outright, the second is plausible but simply absent. A working verifier
    # calls them `supported` and `not_found` respectively -- if the second comes
    # back `supported`, the model is leaning on world knowledge instead of
    # reading the source, and the prompt needs work.
    #
    #   python src/verify.py           real API, needs GEMINI_API_KEY
    #   python src/verify.py --stub    offline, no key, free, tests wiring only
    import argparse

    parser = argparse.ArgumentParser(description="Smoke-test the claim verifier.")
    parser.add_argument(
        "--stub",
        action="store_true",
        help="Use the offline stub client: no API key, no cost, no real judgement.",
    )
    args = parser.parse_args()

    if args.stub:
        from stubs import StubClient

        client = StubClient()
        print("STUB MODE -- string matching, not judgement. Numbers here mean nothing.\n")
    else:
        client = genai.Client()

    source = (
        "Acme Corp today announced Acme Cloud, priced at $49 per seat per month "
        "with an annual commitment. The launch was covered by TechCrunch and "
        "The Verge. Acme said the product had been in private beta since March."
    )

    cases = [
        Claim(text="Acme Cloud costs $49 per seat per month.", source_url="https://example.com/pr"),
        Claim(text="Acme Cloud has over 10,000 customers.", source_url="https://example.com/pr"),
    ]

    total = 0.0
    for claim in cases:
        verdict, usage = verify_claim(client, claim, source)
        total += estimate_cost(VERIFIER_MODEL, usage)
        print(f"claim   : {claim.text}")
        print(f"status  : {verdict.status} ({verdict.confidence})")
        print(f"evidence: {verdict.evidence or '--'}")
        print(f"why     : {verdict.reasoning}\n")

    label = "notional cost (stub, nothing billed)" if args.stub else "verification cost"
    print(f"{label}: ${total:.6f}")
