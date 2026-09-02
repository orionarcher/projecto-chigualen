"""Data sources page — what each source is, and how conflicts are decided."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.data import SOURCES, load_consolidated, load_contested, load_long
from app.backbone import registered

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from _sources import (  # noqa: E402
    CITES_DISTINCTION,
    CONTEST_CLASSES,
    NOT_COMPARED,
    REGISTRY,
)

KIND_LABEL = {
    "backbone": "Taxonomic backbone",
    "regulatory": "Regulatory",
    "curated": "Curated by the project team",
    "custom": "Your own checklist",
}


def render_source_card(source_id: str) -> None:
    s = REGISTRY[source_id]
    with st.container(border=True):
        st.markdown(
            f"<h3 style='margin:0 0 2px 0;'>{s.label} "
            f"<code style='font-size:0.6em; vertical-align:middle;'>{s.id}</code></h3>"
            f"<div style='color:{s.colour}; font-weight:600; font-size:0.85em;"
            f" text-transform:uppercase; letter-spacing:0.04em;'>"
            f"{KIND_LABEL.get(s.kind, s.kind)}</div>",
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
            f"**Licence / terms:** {s.licence}",
            f"**Row types:** {', '.join(f'`{r}`' for r in s.relations)}",
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

    st.subheader("The two CITES sources are different things")
    st.markdown(
        "This is the distinction that trips people up most often, so it is worth "
        "stating plainly. **`cites_csv` and `cites_pdf` are not two formats of one "
        "dataset.** They answer different questions and neither substitutes for "
        "the other."
    )
    st.markdown(
        "| | `cites_csv` — the listings | `cites_pdf` — the checklist |\n"
        "|---|---|---|\n"
        + "".join(f"| **{q}** | {a} | {b} |\n" for q, a, b in CITES_DISTINCTION)
    )
    st.markdown(
        """
The practical consequence: a name can be **accepted in `cites_csv` and a synonym
everywhere else**, because the listings table records the name under which a
taxon is regulated, not the name a botanist would use today. That is the single
most common cause of a `status_conflict`, and it is a real regulatory fact
rather than a data error — which is why such names are surfaced rather than
silently resolved.
        """
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
    st.subheader("How `contest_class` is decided")
    st.markdown(
        "When sources cannot be reconciled on a name, the name is held out of "
        "the consolidated table and written to `contested_names.csv` instead — "
        "one row per source, so you can see who said what. `contest_class` "
        "records **which comparison failed**."
    )

    for cls in CONTEST_CLASSES:
        with st.container(border=True):
            st.markdown(
                f"<span style='display:inline-block; padding:2px 10px; border-radius:12px;"
                f" background:{cls.colour}22; color:{cls.colour}; font-weight:600;"
                f" border:1px solid {cls.colour}55; font-family:monospace;'>{cls.id}</span>"
                f" &nbsp; <b>{cls.headline}</b>",
                unsafe_allow_html=True,
            )
            st.markdown(cls.definition)
            st.markdown(f"**Fields compared:** {cls.compared}")
            st.caption(f"Example — {cls.example}")

    st.markdown("#### What is deliberately *not* compared")
    for title, body in NOT_COMPARED:
        st.markdown(f"**{title}.** {body}")

    st.divider()
    st.subheader("Coming: CITES Standard Nomenclatures")
    st.markdown(
        """
Machine-readable editions of the **CITES Standard Nomenclatures**, current and
historical, are the obvious next sources to add: they are the reference the
Parties actually adopted, and historical editions would let a name be checked
against the nomenclature that was in force at the time a permit was issued.

The pipeline is already shaped for this. Adding a source means:

1. write a cleaner that emits `Chigualen/data/clean/<id>.csv` in the frozen
   schema in `scripts/_normalize.py`;
2. append one `Source(...)` entry to `scripts/_sources.py` — that is what fills
   in this page, the colour coding, and the export columns;
3. add its id to `PIPELINE_ORDER` at the priority it deserves.

Nothing else needs to change: consolidation, the conflict classes, the species
cards and the batch export all read the registry. A historical edition would
enter as its own source (`cites_nomenclature_2019`, say) rather than replacing
the current one, so an edition-to-edition disagreement would surface as an
ordinary `status_conflict` you could read off the per-source columns.
        """
    )

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
