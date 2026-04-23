"""Ingest page: upload an authority CSV, map columns, diff against the DB."""

from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from app.data import (
    build_search_index,
    normalize_query,
)

NONE_CHOICE = "— (none) —"


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
    # Prefer comma; fall back to tab if comma-only gives one column
    df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    if df.shape[1] == 1:
        df2 = pd.read_csv(io.StringIO(text), sep="\t", dtype=str, keep_default_na=False)
        if df2.shape[1] > 1:
            df = df2
    return df


def _diff_row(query: str, index: dict[str, dict]) -> tuple[str, str, str, str]:
    """Return (category, canonical_name, synonym_type, detail) for a single query.

    category ∈ {matched_accepted, matched_synonym, contested, missing, unparseable}
    """
    normalized = normalize_query(query)
    if not normalized:
        return ("unparseable", "", "", "fewer than 2 tokens or empty")
    key = normalized.lower()
    entry = index.get(key)
    if entry is None:
        return ("missing", "", "", "")
    mt = entry["match_type"]
    if mt == "accepted":
        return ("matched_accepted", entry["canonical"], "", "")
    if mt == "synonym":
        return ("matched_synonym", entry["canonical"], entry.get("synonym_type", ""),
                entry.get("synonym_sources", ""))
    if mt == "contested":
        return ("contested", entry["canonical"], "", "")
    return ("missing", "", "", "")


def _download_button(df: pd.DataFrame, filename: str, label: str) -> None:
    st.download_button(
        label=label,
        data=df.to_csv(index=False).encode("utf-8"),
        file_name=filename,
        mime="text/csv",
    )


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
    # Heuristic default for `name`: first column containing 'name' or 'species'
    name_default = 1  # first real col
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

    can_analyze = name_col != NONE_CHOICE
    if not can_analyze:
        st.warning("Map a name column to enable analysis.")
        return

    if not st.button("Analyze", type="primary"):
        return

    # ---- run diff ----
    index = build_search_index()

    categories: list[str] = []
    canonicals: list[str] = []
    syn_types: list[str] = []
    details: list[str] = []
    for v in df[name_col].tolist():
        cat, canon, syn_t, detail = _diff_row(v, index)
        categories.append(cat)
        canonicals.append(canon)
        syn_types.append(syn_t)
        details.append(detail)

    result = df.copy()
    result["diff_category"] = categories
    result["matched_accepted_name"] = canonicals
    result["synonym_type"] = syn_types
    result["match_notes"] = details

    # ---- summary ----
    st.divider()
    st.subheader(
        f"Diff summary — {authority_label or 'authority'} ({len(result)} rows)"
    )
    counts = pd.Series(categories).value_counts().to_dict()
    summary_labels = [
        ("matched_accepted", "Matched (accepted)", "#2e7d32"),
        ("matched_synonym", "Matched (synonym)", "#1565c0"),
        ("contested", "Contested", "#ef6c00"),
        ("missing", "Missing", "#c62828"),
        ("unparseable", "Unparseable", "#546e7a"),
    ]
    summary_cols = st.columns(len(summary_labels))
    for col, (key, label, color) in zip(summary_cols, summary_labels):
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

    # Full report download (once, at the top)
    fname_base = (authority_label or "authority").replace(" ", "_").lower()
    _download_button(result, f"summary_{fname_base}.csv", "Download full diff CSV")

    # ---- category panels ----
    sections: list[tuple[str, str, list[str]]] = [
        ("matched_accepted", "✓ Matched (accepted names)",
         ["matched_accepted_name"]),
        ("matched_synonym", "↻ Matched (as synonyms)",
         ["matched_accepted_name", "synonym_type", "match_notes"]),
        ("contested", "⚠ Contested",
         ["matched_accepted_name"]),
        ("missing", "✗ Missing",
         []),
        ("unparseable", "— Unparseable",
         ["match_notes"]),
    ]
    for key, title, extra_cols in sections:
        subset = result[result["diff_category"] == key]
        if subset.empty:
            continue
        with st.expander(f"{title} · {len(subset)}"):
            # Show the original name col first, then any useful extras
            display_cols = [name_col] + extra_cols
            # Include user-mapped optional fields for context
            for opt_col in [authority_col, cites_col, distribution_col, notes_col]:
                if opt_col != NONE_CHOICE and opt_col not in display_cols:
                    display_cols.append(opt_col)
            display_cols = [c for c in display_cols if c in subset.columns]
            st.dataframe(subset[display_cols], hide_index=True, use_container_width=True)
            _download_button(subset, f"{key}_{fname_base}.csv", f"Download {key} CSV")
