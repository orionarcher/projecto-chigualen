"""Chigualen orchid consolidation — local Streamlit app.

Run from project root:
    streamlit run archive/app/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Make `app` importable when Streamlit runs this file directly. That is
# archive/, the package's own parent — not the repo root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import backbone, ingest, search, sources_page  # noqa: E402

st.set_page_config(
    page_title="Chigualen — Orchid Consolidation",
    page_icon="🌸",
    layout="wide",
)

css_path = Path(__file__).parent / "styles.css"
if css_path.exists():
    st.markdown(f"<style>{css_path.read_text()}</style>", unsafe_allow_html=True)

PAGES = ["Search", "Ingest authority CSV", "Your own checklists", "Data sources", "About"]

with st.sidebar:
    st.markdown("## 🌸 Projecto Chigualen")
    st.caption("Orchid species consolidation")
    page = st.radio("Navigation", PAGES, label_visibility="collapsed")
    st.divider()
    loaded = backbone.registered()
    if loaded:
        st.markdown(
            "<div style='font-size:0.85em; color:#78909c;'><b>Your checklists</b><br>"
            + "<br>".join(f"{bb.label} — {bb.n_names:,} names" for bb in loaded.values())
            + "</div>",
            unsafe_allow_html=True,
        )
        st.divider()
    st.markdown(
        "<div style='font-size:0.85em; color:#78909c;'>"
        "Data sources: WCVP · WFO · CITES listings CSV · CITES Appendix II PDF · "
        "curated synonyms<br><br>"
        "See <b>Data sources</b> for what each one is authoritative for and how "
        "conflicts are classified."
        "</div>",
        unsafe_allow_html=True,
    )

if page == "Search":
    search.render()
elif page == "Ingest authority CSV":
    ingest.render()
elif page == "Your own checklists":
    backbone.render()
elif page == "Data sources":
    sources_page.render()
elif page == "About":
    st.title("About Chigualen")
    st.markdown(
        """
        This app sits on top of the consolidated orchid-species database built
        from five sources. It is **read-only** — uploads are diff'd against the
        database and reports are offered for download, but nothing is written
        back into the pipeline, and nothing you upload leaves your machine.

        **Search** — find a species by its current accepted name or by any known
        synonym. Synonyms redirect to the accepted species, and every result
        shows what each source says on its own.

        **Ingest** — upload a list from another authority and see which names
        match, which are synonyms, which are missing, and which are contested.
        Each row of the export carries a status and accepted name **per source**,
        plus the reason any contested name is contested and the description year.

        **Your own checklists** — load an authority's internal backbone (WISIA,
        a national checklist) and it is compared alongside the five built-in
        sources everywhere in the app.

        **Data sources** — what each source is, where it comes from, what it is
        authoritative for, and the exact rules behind `contest_class`.
        """
    )

    st.divider()
    from app.data import load_consolidated, load_contested, load_long

    wide = load_consolidated()
    long_df = load_long()
    contested = load_contested()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Accepted species", f"{len(wide):,}")
    c2.metric("Synonym pairs", f"{(long_df['relation'] == 'synonym_of').sum():,}")
    c3.metric("Contested binomials", f"{contested['binomial'].nunique():,}")
    c4.metric("With description year", f"{(wide['description_year'] != '').sum():,}")
