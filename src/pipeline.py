"""
Stages 3 and 4 for the brief path -- verify, then assemble.

This module exists to close a real gap. research.py drafts a brief where every
sentence is tagged with the source it came from, and verify.py can check one claim
against one source, but nothing joined them: the eval measured the question path
instead, and the four-stage pipeline the docs describe was only three stages in
practice.

It lives in its own file rather than in verify.py because research.py already
imports verify.py -- putting the bridge in verify would make that circular.

The thing worth understanding: **a source tag is not proof**. `[S2]` records that
the model was looking at source 2 when it wrote the sentence. Whether S2 actually
supports the sentence is a different question, and answering it is what this does.
The two come apart more often than you would expect -- the model reads a pricing
page and writes a sentence about customer counts the page never mentions.
"""

from dataclasses import dataclass

from research import Brief
from verify import (
    Claim,
    VERIFIER_MODEL,
    TokenUsage,
    Verdict,
    estimate_cost,
    verify_claim,
)


@dataclass
class Checked:
    """One sentence of a brief, after checking it against its cited sources."""

    text: str
    source_ids: list[str]
    verdict: Verdict | None      # None when there was nothing to check against
    is_heading: bool = False

    @property
    def kept(self) -> bool:
        """Headings pass through as structure. Prose must earn its place."""
        if self.is_heading:
            return True
        return self.verdict is not None and self.verdict.status == "supported"

    @property
    def badge(self) -> str:
        if self.is_heading or self.verdict is None:
            return ""
        return {"high": "", "medium": " *(medium confidence)*",
                "low": " *(thin evidence)*"}[self.verdict.confidence]


@dataclass
class Assembled:
    checked: list[Checked]
    usage: TokenUsage
    cost: float

    @property
    def prose(self) -> list[Checked]:
        return [c for c in self.checked if not c.is_heading]

    @property
    def kept(self) -> list[Checked]:
        return [c for c in self.prose if c.kept]

    @property
    def dropped(self) -> list[Checked]:
        return [c for c in self.prose if not c.kept]

    @property
    def survival(self) -> float:
        return len(self.kept) / len(self.prose) if self.prose else 0.0

    @property
    def too_thin(self) -> bool:
        """Whether to tell the reader the brief is not worth relying on.

        Saying "not enough public data" is a feature. A brief where half the
        claims failed verification should say so rather than presenting the
        survivors as though they were the whole picture.
        """
        return len(self.kept) < 3 or self.survival < 0.5

    def markdown(self) -> str:
        out = []
        for c in self.checked:
            if c.is_heading:
                out.append(f"\n**{c.text.lstrip('# ').strip()}**\n")
            elif c.kept:
                cites = " ".join(f"`{s}`" for s in c.source_ids)
                # Source pages often already use "- " for list items, which would
                # render as "- - Free: $0". Strip any leading bullet before adding
                # ours.
                body = c.text.lstrip("-*\u2022 ").strip()
                out.append(f"- {body}{c.badge} {cites}")
        return "\n".join(out).strip()


def verify_brief(client, brief: Brief, model: str = VERIFIER_MODEL) -> Assembled:
    """Check every tagged sentence in a brief against the sources it cites.

    A sentence citing several sources is checked against each until one supports
    it -- the claim only needs to be true of one cited page, and requiring all of
    them would reject correct multi-source claims.

    An untagged sentence gets verdict None and is dropped. It is not verifiable
    even in principle: there is no stated source to check it against, so keeping
    it would mean asserting something on the model's word alone -- exactly what
    this pipeline exists to prevent.
    """
    by_id = {s.id: s for s in brief.sources}
    checked: list[Checked] = []
    total_in = total_out = 0
    cost = 0.0

    for text, tags in brief.tagged_sentences():
        if text.lstrip().startswith("#") or (len(text.split()) <= 3 and not tags):
            checked.append(Checked(text=text, source_ids=tags, verdict=None, is_heading=True))
            continue

        verdict = None
        for tag in tags:
            src = by_id.get(tag)
            if not src or not src.ok:
                continue
            v, usage = verify_claim(client, Claim(text=text, source_url=src.url),
                                    src.text, model=model)
            total_in += usage.input_tokens
            total_out += usage.output_tokens
            cost += estimate_cost(model, usage)
            if verdict is None or v.status == "supported":
                verdict = v
            if v.status == "supported":
                break

        checked.append(Checked(text=text, source_ids=tags, verdict=verdict))

    return Assembled(checked=checked, usage=TokenUsage(total_in, total_out), cost=cost)
