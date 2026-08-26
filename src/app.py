"""
Launch Intel -- the user-facing brief.

    streamlit run src/app.py

Shows the assembled brief, and deliberately shows what was thrown away too. The
dropped-claims panel is not a debug view: a reader deciding whether to trust this
needs to see that verification is really happening and what it caught. A tool that
silently filters is asking for the same blind faith as one that never checked.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from google import genai

from pipeline import verify_brief
from research import get_sources, load_source_urls, save_brief, write_brief

st.set_page_config(page_title="Launch Intel", page_icon="🔍", layout="centered")

st.title("Launch Intel")
st.caption(
    "Competitive briefs that cite their sources — and drop the claims those "
    "sources don't support."
)

try:
    import json
    known = [k for k in json.load(open(Path(__file__).parent.parent / "sources.json"))
             if not k.startswith("_")]
except Exception:
    known = []

company = st.selectbox("Company", known) if known else st.text_input("Company")
go = st.button("Build brief", type="primary", disabled=not company)

if go:
    client = genai.Client()

    with st.status("Working...", expanded=True) as status:
        st.write("Reading sources...")
        sources = get_sources(company, load_source_urls(company))
        ok = [s for s in sources if s.ok]
        st.write(f"{len(ok)} of {len(sources)} sources readable")

        st.write("Drafting the brief...")
        brief = write_brief(client, company, sources)
        save_brief(brief)

        st.write("Verifying each claim against its cited source...")
        result = verify_brief(client, brief)
        status.update(label="Done", state="complete", expanded=False)

    # The honest-gap path. If most claims failed verification, say so up front
    # rather than presenting the survivors as if they were the whole picture.
    if result.too_thin:
        st.warning(
            f"**Not enough verifiable public data on {company}.** Only "
            f"{len(result.kept)} of {len(result.prose)} claims held up against "
            "their sources. Treat the brief below as fragments, not a briefing."
        )

    c1, c2, c3 = st.columns(3)
    c1.metric("Claims kept", f"{len(result.kept)}/{len(result.prose)}")
    c2.metric("Survived verification", f"{result.survival:.0%}")
    c3.metric("Cost", f"${brief.cost + result.cost:.4f}")

    st.markdown(result.markdown())

    if result.dropped:
        with st.expander(f"Dropped {len(result.dropped)} claim(s) — why", expanded=False):
            st.caption(
                "These were written by the model but not supported by the source "
                "they cited. This is the failure the tool exists to catch."
            )
            for c in result.dropped:
                verdict = c.verdict.status if c.verdict else "no source cited"
                st.markdown(f"**`{verdict}`** — {c.text}")
                if c.verdict and c.verdict.reasoning:
                    st.caption(c.verdict.reasoning)
    else:
        st.success("Every claim was supported by the source it cited.")

    with st.expander("Sources"):
        for s in brief.sources:
            state = s.error or ("truncated" if s.truncated else f"{len(s.text):,} chars")
            st.markdown(f"**`{s.id}`** [{s.title or s.url}]({s.url}) — {state}")

    st.caption(
        "A source tag records where the model was looking, not that the page "
        "supports the sentence. Every claim above was re-checked against its "
        "cited source; anything that failed is in the dropped panel."
    )
