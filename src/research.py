"""
Stage 1 -- the researcher.

Reads a fixed set of public pages for a company and writes a draft GTM brief
from them, with every factual sentence tagged to the source it came from.

Why we fetch pages ourselves instead of using Google Search grounding: grounding
is not available on the Gemini free tier (it returns a 429 quota error the moment
the `google_search` tool is attached, on every model). But this turned out to be
the better architecture anyway, for a reason that matters to the whole project:

    The source set is fixed and cached, so when the eval score moves between
    Day 5 and Day 10, it moved because of your work -- not because a search
    result changed underneath you.

With grounding you get a different source set on every run, which makes a
before/after comparison much weaker. The cost is losing discovery: this only
reads pages you list in sources.json, so it will never surface something you
didn't think to include. That is a real limitation and belongs in the Day 14
write-up rather than being hidden.

It also buys an exact claim-to-source binding. Because we label each page `S1`,
`S2` ... and require the model to tag every sentence, stage 2 gets a precise
mapping instead of the approximate character-span annotations grounding returns.

Two things to understand about the output.

First, it is not trustworthy yet, and it will not look untrustworthy. The brief
reads like something a consultant charged for -- confident, specific, tidy. Parts
of it will be wrong in ways you cannot see. That is not a prompt bug to fix here;
it is why stages 2 and 3 exist.

Second, a source tag is not proof. `[S2]` means the model says this came from
source 2. Whether S2 actually supports the sentence is verify.py's job, and the
two come apart more often than you would expect.
"""

import argparse
import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import io

import pypdf
import requests
from bs4 import BeautifulSoup
from google import genai
from pydantic import BaseModel, Field

# Reuse rather than redefine -- model choice, pricing and the cost helper live in
# verify.py and must not drift between the two stages.
from verify import SYNTHESIS_MODEL, TokenUsage, estimate_cost

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
SOURCES_CONFIG = ROOT / "sources.json"

# Per-source character cap. Flash has a large context window so this is about
# cost and signal-to-noise, not capacity: past ~20k chars a marketing page is
# mostly nav, footer and boilerplate. Truncation is always reported, never
# silent -- a brief built on a cut-off page should say so.
MAX_CHARS = 20_000

# Identify the fetcher honestly and don't hammer anyone's server.
HEADERS = {"User-Agent": "launch-intel/0.1 (research prototype; contact via repo)"}
POLITE_DELAY = 1.0

BRIEF_SYSTEM = """\
You write short, factual go-to-market briefs on competitors for a product team.

You will be given numbered sources (S1, S2, ...). Use only those. You have no
other information -- if something is not in the sources, you do not know it.

Cover only these sections, in this order. Omit any section the sources do not
support.

  Positioning      -- how the company describes itself, and who it targets
  Differentiators  -- what it claims sets it apart
  Pricing          -- published prices, tiers, and billing model
  Channels         -- where its recent launches got attention

Rules that matter more than completeness:

- End every factual sentence with the tag of the source it came from, like [S2].
  A sentence drawing on two sources gets both: [S1][S3].
- Never write a tag for a source that does not actually state the fact. An
  untagged sentence is far better than a wrongly tagged one.
- Write "not stated in the sources" rather than estimating. Never infer a figure
  from a range, from a competitor, or from general knowledge of the market.
- A short brief on solid sources is correct output. Do not pad a thin section to
  make it look complete.
- No preamble, no description of what you are about to do, no closing summary.
  Start with the first section heading."""


ANSWER_SYSTEM_STRICT = """\
You answer one question about a company using only the numbered sources given.

You have no other information. If the sources do not state the answer, you do not
know it -- and saying so is the correct, expected outcome, not a failure. Many
questions have no answer in the sources by design.

Set `answered` to true ONLY if a source actually states the answer. Not if it
implies it, not if it feels likely, not if you happen to know it from elsewhere.

Traps to refuse rather than guess:
- A figure the sources never give, even if you could estimate it from what they do
- A general claim you would be inferring from examples (customer logos are not a
  statement about who the company targets)
- Something stated about one product or tier, applied to another

When answered is false, leave `answer` empty. Do not explain the company instead.
When answered is true, keep the answer to one or two sentences and list every
source id that supports it."""


# The default answering prompt, chosen on evidence rather than instinct.
#
# ANSWER_SYSTEM_STRICT above refused any question containing a superlative -- "the
# primary differentiator", "announced most recently" -- because no page ranks its
# features or orders its announcements. Literally true, and it cost real coverage:
#
#                     strict      this one
#   correct           8/10 (80%)  9/10 (90%)
#   false refusal     2/10 (20%)  0/10 (0%)
#   fabrication       0/7  (0%)   0/7  (0%)
#
# Strictness bought no safety on this set -- fabrication stayed at zero either
# way -- while costing two answerable rows. Hence the default.
#
# The line this draws is direct reading versus guessing, not literal wording
# versus meaning. Keep ANSWER_SYSTEM_STRICT around: if a later change pushes
# fabrication above zero, it is the fallback, and re-running against it is how
# you show the tradeoff still holds.
ANSWER_SYSTEM = """\
You answer one question about a company using only the numbered sources given.

You have no other information. If the sources do not support an answer, say so --
that is a correct outcome, not a failure, and many questions have no answer here.

Answer when a source states the answer, or when it follows directly and
unambiguously from what a source says. A homepage that leads with one claim is
naming what it emphasises; a dated post is evidence of when something happened.
You do not need the source to use the exact words of the question.

Still refuse when answering would mean inventing:
- A figure no source gives, even one you could estimate from what they do give
- A generalisation drawn from examples (customer logos are not a statement about
  who the company targets)
- Something stated about one product or tier, applied to another
- A ranking or ordering across sources that give you no basis to compare

The line is direct reading versus guessing, not literal wording versus meaning.

When answered is false, leave `answer` empty. Do not explain the company instead.
When answered is true, keep the answer to one or two sentences and list every
source id that supports it."""


class SourcedAnswer(BaseModel):
    """A question answered from the sources -- or explicitly not answered."""

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


@dataclass
class Source:
    id: str
    url: str
    title: str = ""
    text: str = ""
    truncated: bool = False
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.text.strip())


@dataclass
class Brief:
    company: str
    text: str = ""
    sources: list[Source] = field(default_factory=list)
    model: str = SYNTHESIS_MODEL
    fetched_at: str = ""
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def usage(self) -> TokenUsage:
        return TokenUsage(self.input_tokens, self.output_tokens)

    @property
    def cost(self) -> float:
        return estimate_cost(self.model, self.usage)

    def tagged_sentences(self) -> list[tuple[str, list[str]]]:
        """Split the brief into sentences paired with the source ids they cite.

        This is the rough input to stage 2. It is not the finished claim list --
        a sentence can hold two claims, and headings hold none -- but it is the
        exact source binding that stage 2 refines.
        """
        out = []
        # Split on newlines as well as sentence ends -- headings carry no full
        # stop, so punctuation alone glues a heading onto the sentence after it.
        for raw in re.split(r"(?<=[.!?])\s+|\n+", self.text):
            sentence = raw.strip()
            if not sentence:
                continue
            tags = re.findall(r"\[(S\d+)\]", sentence)
            clean = re.sub(r"\s*\[S\d+\]", "", sentence).strip()
            if clean:
                out.append((clean, tags))
        return out

    def untagged_fraction(self) -> float:
        """Share of prose sentences carrying no source tag.

        Watch this from day one. A high number means the model is asserting
        things it credits to nothing -- and stage 2 has to make a decision about
        those: drop them, or check them against every source?
        """
        prose = [
            (s, t) for s, t in self.tagged_sentences()
            if not s.startswith("#") and len(s.split()) > 3
        ]
        if not prose:
            return 0.0
        return sum(1 for _, tags in prose if not tags) / len(prose)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def fetch(url: str, source_id: str) -> Source:
    """Fetch one page and reduce it to readable text.

    Failures are captured on the Source rather than raised. One dead link should
    degrade a brief, not abort the run -- and the error needs to survive into the
    cache so you can see later which pages were missing when a brief was written.
    """
    src = Source(id=source_id, url=url)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as exc:
        src.error = f"{type(exc).__name__}: {exc}"
        return src

    ctype = resp.headers.get("content-type", "").lower()

    # PDFs must be handled before anything touches resp.text. Decoding PDF bytes
    # as text yields 11k characters of binary sludge that BeautifulSoup happily
    # accepts -- the fetch reports success and the model receives garbage as its
    # source. A silent wrong answer is worse than a crash, so branch here.
    if "application/pdf" in ctype or url.lower().split("?")[0].endswith(".pdf"):
        try:
            reader = pypdf.PdfReader(io.BytesIO(resp.content))
            pages = [(pg.extract_text() or "") for pg in reader.pages]
        except Exception as exc:
            src.error = f"PDF parse failed: {type(exc).__name__}: {exc}"
            return src

        src.title = (reader.metadata or {}).get("/Title") or url
        text = re.sub(r"\n{3,}", "\n\n", "\n\n".join(pages).strip())
        if not text:
            # Scanned filings are images of text. OCR is out of scope; say so
            # rather than pass an empty source along as if it were usable.
            src.error = f"PDF has no extractable text ({len(reader.pages)} pages, likely scanned)"
            return src
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS]
            src.truncated = True
        src.text = text
        return src

    soup = BeautifulSoup(resp.text, "html.parser")
    # Strip the furniture before extracting text, or every page arrives as a pile
    # of nav links and cookie notices that crowd out the actual content.
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "svg"]):
        tag.decompose()

    src.title = (soup.title.get_text(strip=True) if soup.title else "") or url
    text = re.sub(r"\n{3,}", "\n\n", soup.get_text("\n", strip=True))

    # Any other binary format (images, zip, docx) would also decode to noise.
    # Cheap sanity check: real prose is overwhelmingly printable.
    printable = sum(c.isprintable() or c.isspace() for c in text[:2000])
    if text and printable / min(len(text), 2000) < 0.9:
        src.error = f"content is not text (content-type: {ctype or 'unknown'})"
        return src

    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
        src.truncated = True
    src.text = text
    return src


def load_source_urls(company: str) -> list[str]:
    config = json.loads(SOURCES_CONFIG.read_text())
    for key, urls in config.items():
        if key.startswith("_"):
            continue
        if key.lower() == company.lower():
            return urls
    raise KeyError(
        f"No sources listed for {company!r} in sources.json. "
        f"Add a key, or pass --url. Known: "
        f"{', '.join(k for k in config if not k.startswith('_'))}"
    )


def fetch_sources(urls: list[str]) -> list[Source]:
    sources = []
    for i, url in enumerate(urls, start=1):
        if i > 1:
            time.sleep(POLITE_DELAY)
        src = fetch(url, f"S{i}")
        flag = "ok " if src.ok else "ERR"
        note = " (truncated)" if src.truncated else ""
        print(f"  [{flag}] {src.id} {url}{note}")
        if src.error:
            print(f"        {src.error}")
        sources.append(src)
    return sources


def write_brief(client, company: str, sources: list[Source], model: str = SYNTHESIS_MODEL) -> Brief:
    """Ask the model to write the brief from the fetched pages only."""
    usable = [s for s in sources if s.ok]
    if not usable:
        raise RuntimeError("No sources fetched successfully -- nothing to write from.")

    blocks = "\n\n".join(
        f'<source id="{s.id}" url="{s.url}" title="{s.title}">\n{s.text}\n</source>'
        for s in usable
    )
    interaction = client.interactions.create(
        model=model,
        system_instruction=BRIEF_SYSTEM,
        input=f"Company: {company}\n\n{blocks}\n\nWrite the brief.",
    )

    usage = getattr(interaction, "usage", None)
    return Brief(
        company=company,
        text=(getattr(interaction, "output_text", "") or "").strip(),
        sources=sources,
        model=model,
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        input_tokens=getattr(usage, "total_input_tokens", 0) or 0,
        output_tokens=getattr(usage, "total_output_tokens", 0) or 0,
    )


def save_sources(company: str, sources: list[Source], root: Path = RUNS) -> Path:
    """Cache the fetched pages on their own, independent of any brief.

    Kept separate so the question mode can reuse pages without needing a brief to
    have been written, and so re-asking questions costs no quota at all.
    """
    out = root / slug(company)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "sources.json"
    path.write_text(json.dumps([asdict(s) for s in sources], indent=2))
    return path


def load_cached_sources(company: str, root: Path = RUNS) -> list[Source] | None:
    path = root / slug(company) / "sources.json"
    if not path.exists():
        return None
    return [Source(**s) for s in json.loads(path.read_text())]


def get_sources(company: str, urls: list[str] | None = None, refetch: bool = False) -> list[Source]:
    """Fetched pages for a company, from cache when possible.

    Cache-first is deliberate. Re-fetching costs time and free-tier quota, and --

    more importantly -- changes the source text underneath an eval, which is
    exactly what we gave up search grounding to avoid.
    """
    if not refetch:
        cached = load_cached_sources(company)
        if cached:
            print(f"  (using {len(cached)} cached sources)")
            return cached

    urls = urls or load_source_urls(company)
    print(f"  fetching {len(urls)} sources...")
    sources = fetch_sources(urls)
    save_sources(company, sources)
    return sources


def answer_question(
    client,
    company: str,
    question: str,
    sources: list[Source],
    model: str = SYNTHESIS_MODEL,
    system: str | None = None,
) -> tuple[SourcedAnswer, TokenUsage]:
    """Answer one question from the sources, or refuse.

    Structured output rather than prose, so `answered` is a machine-readable
    signal. The eval runner needs to distinguish "refused" from "answered" without
    grepping text for phrases like "not stated", which would be fragile and would
    quietly miscount every time the model phrased a refusal differently.
    """
    usable = [s for s in sources if s.ok]
    if not usable:
        raise RuntimeError("No sources fetched successfully -- nothing to answer from.")

    blocks = "\n\n".join(
        f'<source id="{s.id}" url="{s.url}" title="{s.title}">\n{s.text}\n</source>'
        for s in usable
    )
    interaction = client.interactions.create(
        model=model,
        system_instruction=system or ANSWER_SYSTEM,
        input=f"Company: {company}\n\n{blocks}\n\nQuestion: {question}",
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": SourcedAnswer.model_json_schema(),
        },
    )
    usage = getattr(interaction, "usage", None)
    return (
        SourcedAnswer.model_validate_json(interaction.output_text),
        TokenUsage(
            getattr(usage, "total_input_tokens", 0) or 0,
            getattr(usage, "total_output_tokens", 0) or 0,
        ),
    )


def save_brief(brief: Brief, root: Path = RUNS) -> Path:
    """Cache the brief and its full source text, so runs are replayable."""
    out = root / slug(brief.company)
    out.mkdir(parents=True, exist_ok=True)
    (out / "brief.json").write_text(json.dumps(asdict(brief), indent=2))

    # A human-readable copy too -- you will read these by eye constantly while
    # tuning the prompt, and JSON is miserable for that.
    lines = [f"# {brief.company}", "", brief.text, "", "## Sources", ""]
    for s in brief.sources:
        state = s.error or ("truncated" if s.truncated else "ok")
        lines.append(f"- **{s.id}** [{s.title}]({s.url}) — {state}")
    (out / "brief.md").write_text("\n".join(lines) + "\n")
    return out


def load_brief(company: str, root: Path = RUNS) -> Brief:
    """Read a cached brief back. This is what the eval runner should use."""
    path = root / slug(company) / "brief.json"
    if not path.exists():
        raise FileNotFoundError(f"No cached brief for {company!r}. Run research first.")
    data = json.loads(path.read_text())
    data["sources"] = [Source(**s) for s in data.get("sources", [])]
    return Brief(**data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Draft a GTM brief on a competitor.")
    parser.add_argument("company", help='Company name, e.g. "Linear"')
    parser.add_argument("--url", action="append", default=[],
                        help="Extra source URL. Repeatable. Overrides sources.json if given.")
    parser.add_argument("--cached", action="store_true",
                        help="Load the saved brief instead of re-writing it (free, instant).")
    parser.add_argument("--question", "-q",
                        help="Answer one question from the sources instead of writing a brief.")
    parser.add_argument("--refetch", action="store_true",
                        help="Re-download the pages even if cached copies exist.")
    args = parser.parse_args()

    # Question mode: the path the eval runner exercises. Answers from the cached
    # sources, or refuses -- and refusing is the right answer surprisingly often.
    if args.question:
        print(f"{args.company} — {args.question}\n")
        sources = get_sources(args.company, args.url or None, refetch=args.refetch)
        ans, usage = answer_question(genai.Client(), args.company, args.question, sources)
        by_id = {s.id: s for s in sources}

        if ans.answered:
            print(f"ANSWERED   {ans.answer}")
            for sid in ans.source_ids:
                src = by_id.get(sid)
                print(f"           {sid}  {src.url if src else '(unknown id)'}")
        else:
            print("REFUSED    not stated in the sources")
        print(f"\nwhy: {ans.reasoning}")
        print(
            f"tokens: {usage.input_tokens} in / {usage.output_tokens} out"
            f" | notional cost: ${estimate_cost(SYNTHESIS_MODEL, usage):.4f}"
        )
        raise SystemExit(0)

    if args.cached:
        brief = load_brief(args.company)
        print(f"(cached, written {brief.fetched_at})\n")
    else:
        print(f"Preparing sources for {args.company}...")
        sources = get_sources(args.company, args.url or None, refetch=args.refetch)
        print("\nWriting brief...\n")
        brief = write_brief(genai.Client(), args.company, sources)
        print(f"(saved to {save_brief(brief)})\n")

    print(brief.text)

    tagged = brief.tagged_sentences()
    print(f"\n--- {len(brief.sources)} sources ---")
    for s in brief.sources:
        state = s.error or ("truncated" if s.truncated else f"{len(s.text)} chars")
        print(f"  {s.id}  {s.url}\n      {state}")
    print(
        f"\nsentences: {len(tagged)}"
        f" | untagged: {brief.untagged_fraction():.0%}"
        f" | tokens: {brief.input_tokens} in / {brief.output_tokens} out"
        f" | cost: ${brief.cost:.4f}"
    )
