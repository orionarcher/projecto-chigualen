"""Search page: query input, result list, species-card rendering."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from app import backbone
from app.data import (
    SOURCES,
    STATUS_ABSENT,
    STATUS_ACCEPTED,
    STATUS_CONTESTED,
    STATUS_SYNONYM,
    build_search_index,
    get_contested_detail,
    load_contest_rules,
    get_species_row,
    normalize_query,
    parse_synonyms_detailed,
    prefix_matches,
    resolve,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from _sources import SOURCE_COLOURS, label as source_label  # noqa: E402

TYPE_COLORS = {
    "Homotypic": "#2e7d32",
    "Heterotypic": "#ad1457",
    "Orthographic variant": "#6d4c41",
    "Nomenclatural": "#455a64",
    "Mixed": "#ef6c00",
    "Unknown": "#78909c",
}

CITES_COLORS = {"I": "#b71c1c", "II": "#ef6c00", "III": "#f9a825"}

STATUS_STYLE = {
    STATUS_ACCEPTED: ("accepted", "#2e7d32"),
    STATUS_SYNONYM: ("synonym", "#1565c0"),
    STATUS_CONTESTED: ("contested", "#c62828"),
    STATUS_ABSENT: ("not in source", "#90a4ae"),
}

CONTEST_HEADLINE = {
    "status_conflict": "Sources disagree about whether this name is accepted at all.",
    "parent_conflict": "Every source calls this a synonym — of different species.",
    "parent_contested": "This name is not itself disputed; the species it belongs to is.",
}


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
    return "".join(chip(p, SOURCE_COLOURS.get(p, "#546e7a")) for p in parts)


SEED_KEY = "search_seed"
NONCE_KEY = "search_nonce"


def goto(name: str) -> None:
    """Jump the search box to another name.

    Streamlit refuses to reassign a widget-backed key once the widget has been
    instantiated, so the query lives in our own `search_seed` and the input is
    re-keyed on each jump. Bumping the nonce makes Streamlit treat it as a fresh
    widget, which is the only way `value=` is honoured again.
    """
    st.session_state[SEED_KEY] = name
    st.session_state[NONCE_KEY] = st.session_state.get(NONCE_KEY, 0) + 1
    st.rerun()


# --------------------------------------------------------------------------
# Per-source panel
# --------------------------------------------------------------------------

def render_per_source(query_binomial: str) -> None:
    """One row per source: what does that source alone say about this name?

    This is the same resolution the batch export writes into its
    `<source>_status` / `<source>_accepted_name` columns, so a single lookup and
    a bulk CSV can never tell different stories.
    """
    res = resolve(query_binomial)
    bb_verdicts = backbone.verdicts_for(res.binomial or query_binomial)
    backbones = backbone.registered()

    rows = []
    for source_id in SOURCES:
        verdict = res.per_source.get(source_id)
        if verdict is None:
            continue
        status_label, _ = STATUS_STYLE.get(verdict.status, (verdict.status, "#546e7a"))
        rows.append({
            "Source": source_label(source_id),
            "id": source_id,
            "Says": status_label,
            "Name it treats as current": verdict.accepted_name,
            "Detail": verdict.detail,
        })
    for bb_id, verdict in bb_verdicts.items():
        status_label, _ = STATUS_STYLE.get(verdict.status, (verdict.status, "#546e7a"))
        rows.append({
            "Source": f"{backbones[bb_id].label} (yours)",
            "id": bb_id,
            "Says": status_label,
            "Name it treats as current": verdict.accepted_name,
            "Detail": verdict.detail,
        })

    st.markdown("### What each source says")
    st.caption(
        f"Resolved for _{res.binomial or query_binomial}_. "
        "`not in source` means that source has no record of this binomial — not "
        "that it rejects the name."
    )
    st.dataframe(
        pd.DataFrame(rows).drop(columns=["id"]),
        hide_index=True,
        use_container_width=True,
    )

    if not backbones:
        st.caption(
            "Add your own checklist on the **Your own checklists** page to see it "
            "compared here."
        )
    else:
        disagreements = [
            f"**{backbones[bb_id].label}** says "
            f"{STATUS_STYLE.get(v.status, (v.status, ''))[0]}"
            + (f" ({v.accepted_name})" if v.accepted_name else "")
            for bb_id, v in bb_verdicts.items()
            if v.status != STATUS_ABSENT
            and (v.accepted_name or "") != (res.accepted_name or "")
        ]
        if disagreements:
            st.warning(
                "Your checklist differs from the consolidated result: "
                + "; ".join(disagreements),
                icon="⚠",
            )


# --------------------------------------------------------------------------
# Banners
# --------------------------------------------------------------------------

def render_redirect_banner(from_name: str, synonym_type: str, sources: str) -> None:
    type_color = TYPE_COLORS.get(synonym_type, "#78909c")
    st.info(f"↻ Redirected from synonym _{from_name}_")
    chips_html = f"{chip(synonym_type, type_color)} &nbsp; {source_chips(sources)}"
    st.markdown(chips_html, unsafe_allow_html=True)


def render_contested_banner(binomial: str) -> None:
    df = get_contested_detail(binomial)
    contest_class = df["contest_class"].iloc[0] if not df.empty else ""
    reason = df["contest_reason"].iloc[0] if not df.empty else ""
    rule = load_contest_rules().get(contest_class, "")

    st.error(
        f"**⚠ Contested name — `{contest_class or 'contested'}`**  \n"
        f"_{binomial}_ is held out of the consolidated database because the "
        f"sources cannot be reconciled on it.",
        icon="⚠",
    )
    if contest_class in CONTEST_HEADLINE:
        st.markdown(f"**{CONTEST_HEADLINE[contest_class]}**")
    if reason:
        st.markdown(f"Here, specifically: {reason}.")
    if rule:
        with st.expander("How this class is decided"):
            st.markdown(rule)
            st.caption(
                "A disagreement about homotypic vs heterotypic typing never "
                "produces a contested name — see the Data sources page."
            )

    if df.empty:
        st.info("No per-source detail rows found.")
        return

    # Where do the sources say this name belongs? Offer a jump to each.
    parents: list[str] = []
    for value in df["source_says_accepted_parent"]:
        for parent in str(value).split("|"):
            parent = parent.strip()
            if parent and parent not in parents:
                parents.append(parent)
    if parents:
        st.markdown("**Species the sources place this name in**")
        cols = st.columns(min(len(parents), 4))
        for i, parent in enumerate(parents):
            with cols[i % len(cols)]:
                if st.button(f"→ {parent}", key=f"goto_{binomial}_{parent}"):
                    goto(parent)

    show_cols = [c for c in [
        "source", "source_says_relation", "source_says_accepted_parent",
        "authority", "synonym_type", "evidence", "source_record_id",
    ] if c in df.columns]
    st.markdown("**Per-source detail**")
    st.dataframe(df[show_cols], hide_index=True, use_container_width=True)
    if "evidence" in df.columns and (df["evidence"] == "implied_by_synonym_row").any():
        st.caption(
            "`implied_by_synonym_row` — that source never published a record "
            "about this name; it only named it as the accepted parent of some "
            "other name. It counts as that source treating the name as accepted, "
            "but it carries no metadata of its own."
        )

    render_per_source(binomial)


# --------------------------------------------------------------------------
# Species card
# --------------------------------------------------------------------------

def render_contested_synonyms(row: pd.Series) -> None:
    """Names some source files under this species but which are contested.

    These are deliberately absent from the `synonyms` list — promoting a
    disputed name to a settled synonym would misrepresent the sources. But
    leaving them out entirely made the species look as though the name had never
    been proposed, which is exactly the wrong impression for permit work.
    """
    raw = row.get("contested_synonyms", "")
    if not raw:
        return
    names = [n.strip() for n in raw.split(",") if n.strip()]
    if not names:
        return

    st.markdown("### Disputed names filed here")
    st.caption(
        f"{len(names)} name{'s' if len(names) != 1 else ''} that at least one "
        f"source places under _{row['accepted_name']}_, but which the sources "
        f"disagree on. They are **not** in the synonym list above, and they are "
        f"**not** in the consolidated database — open one to see who says what."
    )

    detail_rows = []
    for name in names:
        detail = get_contested_detail(name)
        if detail.empty:
            detail_rows.append({"Name": name, "Why contested": "", "Class": ""})
            continue
        detail_rows.append({
            "Name": name,
            "Class": detail["contest_class"].iloc[0],
            "Why contested": detail["contest_reason"].iloc[0],
        })
    st.dataframe(
        pd.DataFrame(detail_rows)[["Name", "Class", "Why contested"]],
        hide_index=True,
        use_container_width=True,
    )
    cols = st.columns(min(len(names), 4))
    for i, name in enumerate(names[:12]):
        with cols[i % len(cols)]:
            if st.button(f"→ {name}", key=f"cs_{row['accepted_name']}_{name}"):
                goto(name)


def render_species_card(row: pd.Series) -> None:
    name = row["accepted_name"]
    full = row.get("accepted_name_full", "")
    authority = row.get("accepted_authority", "")
    cites = row.get("cites_appendix", "")
    syn_count = int(row.get("synonym_count", 0) or 0)
    sources = row.get("sources", "")
    year = row.get("description_year", "")

    # ---- heading ----
    st.markdown(f"<h2 style='margin-bottom:0;'><i>{name}</i></h2>", unsafe_allow_html=True)
    if full and full != name:
        st.markdown(
            f"<div style='color:#546e7a; margin-bottom:12px; font-size:1.05em;'>{full}</div>",
            unsafe_allow_html=True,
        )

    # ---- badges ----
    badges = []
    if cites:
        badges.append(chip(f"CITES {cites}", CITES_COLORS.get(cites, "#78909c")))
    if year:
        badges.append(chip(f"described {year}", "#455a64"))
    n_srcs = len([s for s in sources.replace("|", ",").split(",") if s.strip()])
    badges.append(chip(f"{n_srcs} source{'s' if n_srcs != 1 else ''}", "#455a64"))
    badges.append(chip(f"{syn_count} synonym{'s' if syn_count != 1 else ''}", "#455a64"))
    n_contested = int(row.get("contested_synonym_count", 0) or 0)
    if n_contested:
        badges.append(chip(f"{n_contested} disputed", "#c62828"))
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
    syns = parse_synonyms_detailed(row.get("synonyms_detailed", ""))
    if syns:
        st.markdown("### Synonyms")
        if any(s["type"] == "Mixed" for s in syns):
            st.caption(
                "`Mixed` means sources agree the name is a synonym of this "
                "species but disagree on homotypic vs heterotypic. That is a "
                "typing disagreement, not a contested name."
            )
        st.dataframe(
            pd.DataFrame([
                {"Synonym": s["name"], "Type": s["type"], "Sources": s["sources"]}
                for s in syns
            ]),
            hide_index=True,
            use_container_width=True,
        )

    # ---- contested names filed here ----
    render_contested_synonyms(row)

    # ---- taxonomy + publication ----
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### Taxonomy")
        for label, val in [
            ("Family", row.get("family", "")),
            ("Genus", row.get("genus", "")),
            ("Species epithet", row.get("species", "")),
            ("Rank", row.get("taxon_rank", "")),
            ("Basionym ID", row.get("basionym", "")),
        ]:
            if val:
                st.markdown(f"**{label}:** {val}")

    with col2:
        st.markdown("### Publication")
        if authority:
            st.markdown(f"**Authority:** {authority}")
        if year:
            st.markdown(f"**Description year:** {year}")
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

    # ---- per-source ----
    render_per_source(name)

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
                st.json(json.loads(extras))
            except ValueError:
                st.text(extras)


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------

def render() -> None:
    from app.data import load_consolidated, load_long

    st.title("Search orchids")
    wide = load_consolidated()
    long_df = load_long()
    st.caption(
        f"Type an accepted name or a synonym. The consolidated database has "
        f"{len(wide):,} accepted species and "
        f"{(long_df['relation'] == 'synonym_of').sum():,} synonym pairs across "
        f"{len(SOURCES)} sources."
    )

    index = build_search_index()
    nonce = st.session_state.get(NONCE_KEY, 0)
    query = st.text_input(
        "Search by name",
        value=st.session_state.get(SEED_KEY, ""),
        placeholder="e.g. Dracula chimaera",
        key=f"search_q_{nonce}",
    )

    if not query or len(query.strip()) < 2:
        st.info("Start typing to see matches.")
        return

    suggestions = prefix_matches(query, index, limit=15)
    if not suggestions:
        norm = normalize_query(query)
        if norm and norm.lower() in index:
            suggestions = [index[norm.lower()]["canonical"]]
        else:
            st.warning(f"No match found for '{query}'. Check spelling or try a synonym.")
            return

    default_idx = 0
    q_lower = query.strip().lower()
    for i, s in enumerate(suggestions):
        if s.lower() == q_lower:
            default_idx = i
            break

    selected = st.selectbox("Matches", suggestions, index=default_idx)
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
