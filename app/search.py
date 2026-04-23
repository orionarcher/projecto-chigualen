"""Search page: query input, result list, species-card rendering."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from app.data import (
    build_search_index,
    get_contested_detail,
    get_species_row,
    normalize_query,
    parse_synonyms_detailed,
    prefix_matches,
)

SOURCE_COLORS = {
    "wcvp": "#2e7d32",          # green
    "wfo": "#1565c0",            # blue
    "cites_csv": "#ef6c00",      # amber
    "cites_pdf": "#ef6c00",      # amber (same family)
    "user_synonyms": "#6a1b9a",  # purple
}

TYPE_COLORS = {
    "Homotypic": "#2e7d32",
    "Heterotypic": "#ad1457",
    "Orthographic variant": "#6d4c41",
    "Nomenclatural": "#455a64",
    "Mixed": "#ef6c00",
    "Unknown": "#78909c",
}

CITES_COLORS = {"I": "#b71c1c", "II": "#ef6c00", "III": "#f9a825"}


def chip(label: str, color: str = "#546e7a") -> str:
    return (
        f"<span style='display:inline-block; padding:2px 10px; margin:2px;"
        f" border-radius:12px; background:{color}22; color:{color};"
        f" font-size:0.85em; font-weight:500; border:1px solid {color}55;'>"
        f"{label}</span>"
    )


def source_chips(sources_str: str) -> str:
    if not sources_str:
        return ""
    parts = [p.strip() for p in sources_str.replace("|", ",").split(",") if p.strip()]
    return "".join(chip(p, SOURCE_COLORS.get(p, "#546e7a")) for p in parts)


def render_redirect_banner(from_name: str, synonym_type: str, sources: str) -> None:
    type_color = TYPE_COLORS.get(synonym_type, "#78909c")
    st.info(f"↻ Redirected from synonym _{from_name}_")
    chips_html = f"{chip(synonym_type, type_color)} &nbsp; {source_chips(sources)}"
    st.markdown(chips_html, unsafe_allow_html=True)


def render_contested_banner(binomial: str) -> None:
    st.error(
        f"**⚠ Contested name**  \n_{binomial}_ is classified differently across "
        f"sources and is not in the consolidated database. See per-source details below."
    )
    df = get_contested_detail(binomial)
    if df.empty:
        st.info("No detail rows found.")
        return
    st.dataframe(
        df[["source", "source_says_relation", "source_says_accepted_parent",
             "authority", "synonym_type", "contest_class"]],
        hide_index=True,
        use_container_width=True,
    )


def render_species_card(row: pd.Series) -> None:
    name = row["accepted_name"]
    full = row.get("accepted_name_full", "")
    authority = row.get("accepted_authority", "")
    cites = row.get("cites_appendix", "")
    syn_count = int(row.get("synonym_count", 0) or 0)
    sources = row.get("sources", "")

    # ---- heading ----
    st.markdown(
        f"<h2 style='margin-bottom:0;'><i>{name}</i></h2>",
        unsafe_allow_html=True,
    )
    if full and full != name:
        st.markdown(
            f"<div style='color:#546e7a; margin-bottom:12px; font-size:1.05em;'>{full}</div>",
            unsafe_allow_html=True,
        )

    # ---- badges ----
    badges = []
    if cites:
        c = CITES_COLORS.get(cites, "#78909c")
        badges.append(chip(f"CITES {cites}", c))
    n_srcs = len([s for s in sources.replace("|", ",").split(",") if s.strip()])
    badges.append(chip(f"{n_srcs} source{'s' if n_srcs != 1 else ''}", "#455a64"))
    badges.append(chip(f"{syn_count} synonym{'s' if syn_count != 1 else ''}", "#455a64"))
    st.markdown("<div style='margin-bottom:10px;'>" + "".join(badges) + "</div>",
                unsafe_allow_html=True)

    # ---- sources strip ----
    if sources:
        st.markdown(
            "<div style='margin-bottom:18px;'><b style='color:#546e7a;'>Sources:</b> "
            + source_chips(sources) + "</div>",
            unsafe_allow_html=True,
        )

    # ---- synonyms ----
    detail = row.get("synonyms_detailed", "")
    syns = parse_synonyms_detailed(detail)
    if syns:
        st.markdown("### Synonyms")
        rows_for_table = []
        for s in syns:
            rows_for_table.append({
                "Synonym": s["name"],
                "Type": s["type"],
                "Sources": s["sources"],
            })
        st.dataframe(pd.DataFrame(rows_for_table), hide_index=True, use_container_width=True)

    # ---- taxonomy + publication columns ----
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### Taxonomy")
        fields = [
            ("Family", row.get("family", "")),
            ("Genus", row.get("genus", "")),
            ("Species epithet", row.get("species", "")),
            ("Rank", row.get("taxon_rank", "")),
            ("Basionym ID", row.get("basionym", "")),
        ]
        for label, val in fields:
            if val:
                st.markdown(f"**{label}:** {val}")

    with col2:
        st.markdown("### Publication")
        if authority:
            st.markdown(f"**Authority:** {authority}")
        if row.get("first_published"):
            st.markdown(f"**First published:** {row['first_published']}")
        if row.get("place_of_publication"):
            st.markdown(f"**Place:** {row['place_of_publication']}")

    # ---- distribution ----
    geo = row.get("geographic_area", "")
    if geo:
        st.markdown("### Distribution")
        pieces = [p.strip() for p in geo.split(";") if p.strip()]
        if len(pieces) <= 1:
            st.write(geo)
        else:
            for p in pieces:
                st.markdown(f"- {p}")

    # ---- external links ----
    links = []
    ipni = row.get("wcvp_ipni_id", "")
    if ipni:
        links.append(f"[POWO](https://powo.science.kew.org/results?q={ipni})")
    wfo_id = row.get("wfo_taxon_id", "")
    if wfo_id:
        links.append(f"[World Flora Online](https://www.worldfloraonline.org/taxon/{wfo_id})")
    if links:
        st.markdown("### External")
        st.markdown(" &nbsp; • &nbsp; ".join(links))

    # ---- raw extras ----
    extras = row.get("raw_extras", "")
    if extras:
        with st.expander("Raw metadata"):
            try:
                parsed = json.loads(extras)
                st.json(parsed)
            except ValueError:
                st.text(extras)


def render() -> None:
    st.title("Search orchids")
    st.caption(
        "Type an accepted name or a synonym. The consolidated database has "
        "31,498 accepted species and 37,027 synonym pairs across 5 sources."
    )

    index = build_search_index()
    query = st.text_input("Search by name", placeholder="e.g. Dracula chimaera", key="search_q")

    if not query or len(query.strip()) < 2:
        st.info("Start typing to see matches.")
        return

    suggestions = prefix_matches(query, index, limit=15)
    if not suggestions:
        # Try exact-binomial normalization (handles authority tails)
        norm = normalize_query(query)
        if norm and norm.lower() in index:
            suggestions = [index[norm.lower()]["canonical"]]
        else:
            st.warning(f"No match found for '{query}'. Check spelling or try a synonym.")
            return

    # If there's exactly one strong match (typed string equals a key), auto-select.
    default_idx = 0
    q_lower = query.strip().lower()
    for i, s in enumerate(suggestions):
        if s.lower() == q_lower:
            default_idx = i
            break

    selected = st.selectbox("Matches", suggestions, index=default_idx, key="search_pick")
    if not selected:
        return

    entry = index.get(selected.lower())
    if entry is None:
        st.error("Unexpected state: selection not in index.")
        return

    st.divider()

    if entry["match_type"] == "contested":
        render_contested_banner(selected)
        return

    if entry["match_type"] == "synonym":
        render_redirect_banner(selected, entry["synonym_type"], entry["synonym_sources"])

    canonical_row = get_species_row(entry["canonical"])
    if canonical_row is None:
        st.error(f"Could not find species record for '{entry['canonical']}'.")
        return
    render_species_card(canonical_row)
