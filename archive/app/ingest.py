"""Ingest page: upload an authority CSV, map columns, diff against the DB."""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from app import backbone
from app.data import (
    SOURCES,
    build_search_index,
    per_source_columns,
    resolve,
)

NONE_CHOICE = "— (none) —"

# diff_category → (label, colour). The categories are unchanged; every row now
# also carries the per-source detail that used to require a second, manual
# single-species lookup.
CATEGORIES = [
    ("matched_accepted", "Matched (accepted)", "#2e7d32"),
    ("matched_synonym", "Matched (synonym)", "#1565c0"),
    ("contested", "Contested", "#ef6c00"),
    ("missing", "Missing", "#c62828"),
    ("unparseable", "Unparseable", "#546e7a"),
]

VERDICT_TO_CATEGORY = {
    "accepted": "matched_accepted",
    "synonym": "matched_synonym",
    "contested": "contested",
    "missing": "missing",
    "unparseable": "unparseable",
}


def _read_upload(file) -> pd.DataFrame:
    """Try UTF-8, fall back to Latin-1; auto-detect delimiter."""
    raw = file.read()
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("Could not decode file as UTF-8 or Latin-1.")
    df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    if df.shape[1] == 1:
        df2 = pd.read_csv(io.StringIO(text), sep="\t", dtype=str, keep_default_na=False)
        if df2.shape[1] > 1:
            df = df2
    return df


def _download_button(df: pd.DataFrame, filename: str, label: str, key: str) -> None:
    st.download_button(
        label=label,
        data=df.to_csv(index=False).encode("utf-8"),
        file_name=filename,
        mime="text/csv",
        key=key,
    )


def build_report(names: list[str]) -> pd.DataFrame:
    """One row per input name, fully resolved.

    Every column a reviewer needs to explain a verdict is here — the reason a
    name is contested, the description year, and what each source says on its
    own — so a contested batch no longer has to be re-checked one name at a time
    in the search page.
    """
    index = build_search_index()
    backbones = backbone.registered()

    rows: list[dict[str, str]] = []
    for value in names:
        res = resolve(value, index)
        bb_verdicts = {bb_id: bb.lookup(res.binomial) for bb_id, bb in backbones.items()}
        row: dict[str, str] = {
            "diff_category": VERDICT_TO_CATEGORY.get(res.verdict, res.verdict),
            "normalized_binomial": res.binomial,
            "matched_accepted_name": res.accepted_name,
            "synonym_type": res.synonym_type,
            "description_year": res.description_year,
            "cites_appendix": res.cites_appendix,
            "contest_class": res.contest_class,
            "contest_reason": res.contest_reason,
            "match_notes": res.note,
        }
        row.update(per_source_columns(res, bb_verdicts))
        rows.append(row)
    return pd.DataFrame(rows)


def render() -> None:
    st.title("Ingest an authority CSV")
    st.caption(
        "Compare an external list against the consolidated database. Report-only — "
        "uploads are never written to disk."
    )

    uploaded = st.file_uploader(
        "Upload CSV (or TSV). Required: a column containing the species name.",
        type=["csv", "tsv", "txt"],
    )
    if uploaded is None:
        st.info("Upload a file to begin.")
        return

    try:
        df = _read_upload(uploaded)
    except Exception as e:  # noqa: BLE001 — user-facing error path
        st.error(f"Could not read file: {e}")
        return

    if df.empty:
        st.warning("File parsed but has no rows.")
        return

    st.subheader("Preview")
    st.dataframe(df.head(10), use_container_width=True)

    st.subheader("Column mapping")
    cols = [NONE_CHOICE] + list(df.columns)
    name_default = 1
    for i, c in enumerate(df.columns, start=1):
        if any(k in c.lower() for k in ("scientific", "species_name", "taxon", "name")):
            name_default = i
            break

    name_col = st.selectbox(
        "**Name column** (required — maps to binomial)", cols, index=name_default
    )
    c1, c2 = st.columns(2)
    with c1:
        authority_col = st.selectbox("Authority (optional)", cols, index=0)
        cites_col = st.selectbox("CITES appendix (optional)", cols, index=0)
    with c2:
        distribution_col = st.selectbox("Distribution (optional)", cols, index=0)
        notes_col = st.selectbox("Notes (optional)", cols, index=0)

    authority_label = st.text_input(
        "Authority name (for the report)",
        placeholder="e.g. Sander's List 2024",
    )

    if name_col == NONE_CHOICE:
        st.warning("Map a name column to enable analysis.")
        return

    backbones = backbone.registered()
    if backbones:
        st.success(
            "Your checklists will also get a column pair each: "
            + ", ".join(f"`{bb_id}_status`" for bb_id in backbones)
        )
    else:
        st.caption(
            "Tip: load your own backbone on the **Your own checklists** page and "
            "it gets its own columns in this report too."
        )

    if not st.button("Analyze", type="primary"):
        return

    # ---- run diff ----
    with st.spinner("Resolving names against every source…"):
        report = build_report(df[name_col].tolist())
    result = pd.concat([df.reset_index(drop=True), report], axis=1)

    # ---- summary ----
    st.divider()
    st.subheader(f"Diff summary — {authority_label or 'authority'} ({len(result)} rows)")
    counts = result["diff_category"].value_counts().to_dict()
    summary_cols = st.columns(len(CATEGORIES))
    for col, (key, label, color) in zip(summary_cols, CATEGORIES):
        n = counts.get(key, 0)
        with col:
            st.markdown(
                f"<div style='padding:14px; background:{color}11; border:1px solid {color}44;"
                f" border-radius:6px; text-align:center;'>"
                f"<div style='font-size:1.8em; font-weight:600; color:{color};'>{n}</div>"
                f"<div style='color:{color}; font-size:0.95em;'>{label}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

    source_ids = list(SOURCES) + list(backbones)
    st.caption(
        "Every row carries `contest_class`, `contest_reason`, `description_year`, "
        "and a `_status` / `_accepted_name` pair for each of: "
        + ", ".join(f"`{s}`" for s in source_ids)
        + ". `not_in_source` means that source has no record of the binomial."
    )

    fname_base = (authority_label or "authority").replace(" ", "_").lower()
    _download_button(result, f"summary_{fname_base}.csv",
                     "Download full diff CSV", key="dl_full")

    # ---- why-contested roll-up ----
    contested = result[result["diff_category"] == "contested"]
    if not contested.empty:
        st.markdown("#### Why the contested names are contested")
        breakdown = (
            contested.groupby("contest_class").size()
            .rename_axis("contest_class").reset_index(name="names")
        )
        st.dataframe(breakdown, hide_index=True, use_container_width=True)
        st.caption(
            "`status_conflict` — some source calls the name accepted, another "
            "calls it a synonym. `parent_conflict` — all agree it is a synonym, "
            "of different species. `parent_contested` — the name is fine, the "
            "species it belongs to is disputed. Full rules on the Data sources page."
        )

    # ---- category panels ----
    per_source_cols = [c for c in result.columns
                       if c.endswith("_status") or c.endswith("_accepted_name")]
    sections: list[tuple[str, str, list[str]]] = [
        ("matched_accepted", "✓ Matched (accepted names)",
         ["matched_accepted_name", "description_year", "cites_appendix"]),
        ("matched_synonym", "↻ Matched (as synonyms)",
         ["matched_accepted_name", "synonym_type", "description_year"]),
        ("contested", "⚠ Contested",
         ["normalized_binomial", "contest_class", "contest_reason"]),
        ("missing", "✗ Missing", ["normalized_binomial"]),
        ("unparseable", "— Unparseable", ["match_notes"]),
    ]
    for key, title, extra_cols in sections:
        subset = result[result["diff_category"] == key]
        if subset.empty:
            continue
        with st.expander(f"{title} · {len(subset)}"):
            display_cols = [name_col] + extra_cols
            for opt_col in [authority_col, cites_col, distribution_col, notes_col]:
                if opt_col != NONE_CHOICE and opt_col not in display_cols:
                    display_cols.append(opt_col)
            if key in ("matched_accepted", "matched_synonym", "contested"):
                display_cols += per_source_cols
            display_cols = [c for c in display_cols if c in subset.columns]
            st.dataframe(subset[display_cols], hide_index=True, use_container_width=True)
            _download_button(subset, f"{key}_{fname_base}.csv",
                             f"Download {key} CSV", key=f"dl_{key}")
