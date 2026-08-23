"""
Offline stubs -- run the pipeline with no API key and no spend.

Purpose: build and debug the plumbing (claim extraction, the verify loop,
rendering, the eval runner) before you have a key. Because `verify_claim` takes
its client as an argument, swapping the real client for this one is a one-line
change at the call site and nothing else moves.

The hard limit, and it matters:

    Stub mode tests WIRING, not QUALITY.

The verdicts below come from crude word matching, not judgement. Any accuracy
number stub mode reports is meaningless -- do not put it in the eval report and
do not quote it in an interview. The real before/after result that makes this
project worth showing requires the real API. Stub mode buys you exactly one
thing: the right to defer that until the plumbing already works, so you are not
burning quota to discover a typo in your loop.

Note that the stub returns a JSON *string* in `output_text`, exactly as the real
API does, so `Verdict.model_validate_json` runs for real. If the shape is wrong
you get a validation error here rather than a silent wrong answer later.
"""

import json
import re
from dataclasses import dataclass

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "had",
    "has", "have", "in", "is", "it", "its", "of", "on", "or", "that", "the",
    "to", "was", "were", "will", "with", "over", "per", "than", "more",
}


@dataclass
class StubUsage:
    """Mirrors the two fields `verify_claim` reads off a real usage object."""

    total_input_tokens: int
    total_output_tokens: int


@dataclass
class StubInteraction:
    output_text: str
    usage: StubUsage


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if w not in STOPWORDS}


def _numbers(text: str) -> set[str]:
    """Numeric tokens, normalised so '$10,000' and '10000' compare equal."""
    return {n.replace(",", "") for n in re.findall(r"\d[\d,]*", text)}


def _best_sentence(claim_words: set[str], source_text: str) -> str:
    """The source sentence sharing the most words with the claim, verbatim."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", source_text) if s.strip()]
    if not sentences:
        return ""
    return max(sentences, key=lambda s: len(claim_words & _words(s)))


class _StubInteractions:
    def create(self, *, input, **_kwargs) -> StubInteraction:
        claim = re.search(r"<claim>\n(.*?)\n</claim>", input, re.S)
        source = re.search(r"<source[^>]*>\n(.*?)\n</source>", input, re.S)
        claim_text = claim.group(1) if claim else ""
        source_text = source.group(1) if source else ""

        # Numbers first -- they carry the most signal and are where a real model
        # is most likely to hallucinate. A figure absent from the source is
        # not_found however well the surrounding words line up.
        missing_numbers = _numbers(claim_text) - _numbers(source_text)

        claim_words = _words(claim_text)
        overlap = (
            len(claim_words & _words(source_text)) / len(claim_words)
            if claim_words
            else 0.0
        )

        if missing_numbers:
            status, confidence, evidence = "not_found", "low", ""
            reasoning = f"Figure(s) {sorted(missing_numbers)} do not appear in the source."
        elif overlap >= 0.6:
            status, confidence = "supported", "high"
            evidence = _best_sentence(claim_words, source_text)
            reasoning = f"Strong word overlap ({overlap:.0%}) with the source."
        elif overlap >= 0.4:
            status, confidence = "supported", "medium"
            evidence = _best_sentence(claim_words, source_text)
            reasoning = f"Partial overlap ({overlap:.0%}); a real verifier may disagree."
        else:
            status, confidence, evidence = "not_found", "low", ""
            reasoning = f"Little overlap ({overlap:.0%}) with the source text."

        payload = json.dumps(
            {
                "status": status,
                "confidence": confidence,
                "evidence": evidence,
                "reasoning": f"[STUB] {reasoning}",
            }
        )
        # Rough counts so the cost plumbing has something to add up.
        return StubInteraction(
            output_text=payload,
            usage=StubUsage(
                total_input_tokens=len(input) // 4,
                total_output_tokens=len(payload) // 4,
            ),
        )


class StubClient:
    """Drop-in stand-in for `genai.Client()` on the verify path only."""

    def __init__(self) -> None:
        self.interactions = _StubInteractions()
