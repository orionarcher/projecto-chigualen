"""Data sources page — what each source is, and how conflicts are decided."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.data import SOURCES, load_consolidated, load_contested, load_long
from app.backbone import registered

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from _sources import (  # noqa: E402
    CONTEST_CLASSES,
    REGISTRY,
    TYPING_NEVER_CONTESTS,
)

KIND_LABEL = {
    "backbone": "Taxonomic backbone",
    "regulatory": "Regulatory source",
    "curated": "Curated by the project team",
}


def render_source_card(source_id: str) -> None:
    s = REGISTRY[source_id]
    with st.container(border=True):
        st.markdown(
            f"<div style='color:{s.colour}; font-weight:700; font-size:0.75em;"
            f" text-transform:uppercase; letter-spacing:0.08em;'>"
            f"{KIND_LABEL.get(s.kind, s.kind)}</div>"
            f"<h3 style='margin:2px 0 6px 0;'>{s.label}</h3>",
            unsafe_allow_html=True,
        )
        st.markdown(f"*{s.one_liner}*")

        if not s.provenance_confirmed:
            st.warning(
                "The exact provenance of this file is inferred from its columns "
                "rather than from a documented export — worth confirming with "
                "the project team before citing it.",
                icon="⚠",
            )

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Authoritative for**")
            for item in s.contributes:
                st.markdown(f"- {item}")
        with c2:
            st.markdown("**Does _not_ carry**")
            for item in s.does_not_carry:
                st.markdown(f"- {item}")

        st.markdown("**Where it comes from**")
        st.markdown(s.origin)

        meta = [
            f"**Edition used:** {s.edition}",
            f"**Terms of use:** {s.licence}",
        ]
        if s.cleaner:
            meta.append(f"**Cleaner:** `{s.cleaner}`")
        if s.homepage:
            meta.append(f"[Homepage]({s.homepage})")
        st.caption(" · ".join(meta))

        if s.notes:
            st.info(s.notes, icon="ℹ")


def render() -> None:
    st.title("Data sources")
    st.caption(
        "Five sources go into the consolidated database. They are not "
        "interchangeable — two describe taxonomy, two describe regulation, and "
        "one supplies synonym typing the others cannot."
    )

    st.divider()
    st.subheader("Every source in detail")
    for source_id in SOURCES:
        render_source_card(source_id)

    custom = registered()
    if custom:
        st.markdown("#### Your own checklists (this session)")
        for bb in custom.values():
            st.markdown(
                f"- **{bb.label}** `{bb.id}` — {bb.n_names:,} names, "
                f"compared alongside the five built-in sources."
            )
    else:
        st.info(
            "You can add your own backbone — an authority database such as "
            "WISIA, or any checklist CSV — from the **Your own checklists** "
            "page. It is then compared alongside these five everywhere in the app."
        )

    st.divider()
    st.subheader("How contested names are classified")
    st.markdown(
        "When the sources cannot be reconciled on a name, it is kept out of the "
        "main table and recorded separately, one row per source, so you can see "
        "who said what. The **Contest Class** records which comparison failed."
    )

    for cls in CONTEST_CLASSES:
        with st.container(border=True):
            st.markdown(
                f"<span style='display:inline-block; padding:2px 10px; border-radius:12px;"
                f" background:{cls.colour}22; color:{cls.colour}; font-weight:650;"
                f" border:1px solid {cls.colour}55;'>{cls.title}</span>"
                f" &nbsp; {cls.summary}",
                unsafe_allow_html=True,
            )
            st.caption(cls.detail)
            st.caption(f"Example — {cls.example}")
    st.info(TYPING_NEVER_CONTESTS, icon="ℹ")

    st.divider()
    st.subheader("What is in this build")
    wide = load_consolidated()
    long_df = load_long()
    contested = load_contested()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Accepted species", f"{len(wide):,}")
    c2.metric("Synonym pairs", f"{(long_df['relation'] == 'synonym_of').sum():,}")
    c3.metric("Contested binomials", f"{contested['binomial'].nunique():,}")
    c4.metric("With a description year", f"{(wide['description_year'] != '').sum():,}")

    by_class = (
        contested.drop_duplicates("binomial")["contest_class"]
        .value_counts()
        .rename_axis("contest_class")
        .reset_index(name="binomials")
    )
    st.dataframe(by_class, hide_index=True, use_container_width=True)

    rows = []
    for source_id in SOURCES:
        s = REGISTRY[source_id]
        in_species = wide["sources"].str.contains(source_id, regex=False).sum()
        rows.append({
            "source": source_id,
            "label": s.label,
            "kind": KIND_LABEL.get(s.kind, s.kind),
            "species touched": f"{in_species:,}",
            "licence": s.licence,
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
