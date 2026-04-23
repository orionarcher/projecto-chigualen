"""Chigualen orchid consolidation — local Streamlit app.

Run from project root:
    streamlit run app/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Make `app` importable when Streamlit runs this file directly.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import ingest, search  # noqa: E402

st.set_page_config(
    page_title="Chigualen — Orchid Consolidation",
    page_icon="🌸",
    layout="wide",
)

# Load custom CSS if present
css_path = Path(__file__).parent / "styles.css"
if css_path.exists():
    st.markdown(f"<style>{css_path.read_text()}</style>", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("## 🌸 Projecto Chigualen")
    st.caption("Orchid species consolidation")
    page = st.radio(
        "Navigation",
        ["Search", "Ingest authority CSV", "About"],
        label_visibility="collapsed",
    )
    st.divider()
    st.markdown(
        "<div style='font-size:0.85em; color:#78909c;'>"
        "Data sources: WCVP · WFO · CITES (listings + Appendix II PDF) · user synonyms"
        "</div>",
        unsafe_allow_html=True,
    )

if page == "Search":
    search.render()
elif page == "Ingest authority CSV":
    ingest.render()
elif page == "About":
    st.title("About Chigualen")
    st.markdown(
        """
        This app sits on top of the consolidated orchid-species database built
        from five sources. It is **read-only** — uploads are diff'd against the
        database and reports are offered for download, but nothing is written
        back into the pipeline.

        **Search** — find a species by its current accepted name or by any
        known synonym. Synonyms automatically redirect to the accepted species.

        **Ingest** — upload a CSV from another authority (herbarium, checklist,
        registry) and see which names match, which are synonyms of known
        species, which are missing from our DB, and which are in a contested
        state across sources.
        """
    )
    from app.data import load_consolidated, load_long, load_contested
    wide = load_consolidated()
    long_df = load_long()
    contested = load_contested()
    c1, c2, c3 = st.columns(3)
    c1.metric("Accepted species", f"{len(wide):,}")
    c2.metric("Synonym pairs", f"{(long_df['relation']=='synonym_of').sum():,}")
    c3.metric("Contested rows", f"{len(contested):,}")
