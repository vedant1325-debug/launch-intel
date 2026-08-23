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

Model choice is deliberate and is the project's main cost lever:

    stage 1, synthesis     -> claude-opus-5     hard reasoning, low volume
    stage 3, verification  -> claude-haiku-4-5  easy judgement, high volume

Verification runs once per claim, so a 20-claim brief is 20 calls. Paying Opus
rates to answer "is this sentence supported by this text?" is waste. Haiku is
5x cheaper on both input and output and is entirely capable of the call.
"""

from typing import Literal, Optional

import anthropic
from pydantic import BaseModel, Field

# Per-million-token pricing, used by estimate_cost() for the README cost table.
PRICING = {
    "claude-opus-5": {"input": 5.00, "output": 25.00},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
}

SYNTHESIS_MODEL = "claude-opus-5"
VERIFIER_MODEL = "claude-haiku-4-5"


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


def verify_claim(
    client: anthropic.Anthropic,
    claim: Claim,
    source_text: str,
    model: str = VERIFIER_MODEL,
) -> tuple[Verdict, anthropic.types.Usage]:
    """Check one claim against the text of the source it cites.

    Pure with respect to the network apart from the single API call: the caller
    supplies `source_text`, which keeps this function trivially testable and
    lets the eval harness replay fixed sources without hitting the web.

    Returns the verdict plus the raw usage object, because the cost table in the
    README is a deliverable and we need real token counts to build it.
    """
    # NOTE: we deliberately do NOT use document blocks with
    # `citations: {"enabled": True}` here. Citations and structured outputs are
    # mutually exclusive -- sending both returns a 400. We want the machine-
    # readable verdict, so the source goes in as plain text and we ask the model
    # to quote its evidence into the `evidence` field instead.
    response = client.messages.parse(
        model=model,
        max_tokens=1024,
        system=VERIFIER_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": (
                    f"<claim>\n{claim.text}\n</claim>\n\n"
                    f"<source url=\"{claim.source_url}\">\n{source_text}\n</source>\n\n"
                    "Does the source support the claim?"
                ),
            }
        ],
        output_format=Verdict,
    )
    return response.parsed_output, response.usage


def estimate_cost(model: str, usage: anthropic.types.Usage) -> float:
    """Dollar cost of a single call. Summed across a run to fill the cost table."""
    rates = PRICING[model]
    return (
        usage.input_tokens / 1_000_000 * rates["input"]
        + usage.output_tokens / 1_000_000 * rates["output"]
    )


def render_claim(claim: Claim, verdict: Verdict) -> Optional[str]:
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
    # back `supported`, the prompt is leaking world knowledge and needs work.
    client = anthropic.Anthropic()

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
        print(f"\nclaim   : {claim.text}")
        print(f"status  : {verdict.status} ({verdict.confidence})")
        print(f"evidence: {verdict.evidence or '--'}")
        print(f"why     : {verdict.reasoning}")

    print(f"\ntotal verification cost: ${total:.6f}")
