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

import requests
from bs4 import BeautifulSoup
from google import genai

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

    soup = BeautifulSoup(resp.text, "html.parser")
    # Strip the furniture before extracting text, or every page arrives as a pile
    # of nav links and cookie notices that crowd out the actual content.
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "svg"]):
        tag.decompose()

    src.title = (soup.title.get_text(strip=True) if soup.title else "") or url
    text = re.sub(r"\n{3,}", "\n\n", soup.get_text("\n", strip=True))

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
                        help="Load the saved brief instead of re-fetching (free, instant).")
    args = parser.parse_args()

    if args.cached:
        brief = load_brief(args.company)
        print(f"(cached, written {brief.fetched_at})\n")
    else:
        urls = args.url or load_source_urls(args.company)
        print(f"Fetching {len(urls)} sources for {args.company}...")
        sources = fetch_sources(urls)
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
