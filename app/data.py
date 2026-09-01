"""Cached data loaders, search index, and per-source name resolution."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from _normalize import binomial as make_binomial  # noqa: E402
from _normalize import norm_text  # noqa: E402
from _sources import PIPELINE_ORDER, split_source_list  # noqa: E402

OUT_DIR = ROOT / "Chigualen" / "data" / "out"

CONSOLIDATED_PATH = OUT_DIR / "orchid_synonyms_consolidated.csv"
LONG_PATH = OUT_DIR / "orchid_synonyms_long.csv"
CONTESTED_PATH = OUT_DIR / "contested_names.csv"
CONTEST_RULES_PATH = OUT_DIR / "contest_class_reference.csv"

SOURCES = list(PIPELINE_ORDER)

# Per-source verdicts used across the app and every CSV export.
STATUS_ACCEPTED = "accepted"
STATUS_SYNONYM = "synonym"
STATUS_CONTESTED = "contested"
STATUS_ABSENT = "not_in_source"


@st.cache_data(show_spinner="Loading consolidated species…")
def load_consolidated() -> pd.DataFrame:
    df = pd.read_csv(CONSOLIDATED_PATH, dtype=str, keep_default_na=False)
    for col in ("synonym_count", "contested_synonym_count"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
        else:
            df[col] = 0
    return df


@st.cache_data(show_spinner="Loading synonym pairs…")
def load_long() -> pd.DataFrame:
    return pd.read_csv(LONG_PATH, dtype=str, keep_default_na=False)


@st.cache_data(show_spinner="Loading contested names…")
def load_contested() -> pd.DataFrame:
    df = pd.read_csv(CONTESTED_PATH, dtype=str, keep_default_na=False)
    # Older builds of contested_names.csv predate the explanatory columns.
    for col in ("contest_reason", "evidence",
                "n_sources_accepted", "n_sources_synonym", "all_claimed_parents"):
        if col not in df.columns:
            df[col] = ""
    return df


@st.cache_resource(show_spinner=False)
def load_contest_rules() -> dict[str, str]:
    """contest_class → the rule that produced it.

    Kept in its own three-row file rather than repeated on every one of the 36k
    contested rows, where it tripled the file size for a constant string.
    """
    if not CONTEST_RULES_PATH.exists():
        return {}
    df = pd.read_csv(CONTEST_RULES_PATH, dtype=str, keep_default_na=False)
    return dict(zip(df["contest_class"], df["rule"]))


# --------------------------------------------------------------------------
# Search index
# --------------------------------------------------------------------------

@st.cache_resource(show_spinner="Building search index…")
def build_search_index() -> dict[str, dict]:
    """key = lowercased binomial → entry describing how the DB resolves it.

    entry = {canonical, match_type, synonym_type, synonym_sources, sources}

    Resolution order — later stages overwrite earlier ones:
        1. accepted   (from the long table's accepted rows)
        2. synonym    (from the long table's synonym rows; never beats accepted)
        3. contested  (always wins — the name is held out of the consolidated DB)
    """
    long_df = load_long()
    contested = load_contested()

    index: dict[str, dict] = {}

    accepted = long_df[long_df["relation"] == "accepted"]
    for name, srcs in zip(accepted["accepted_name"], accepted["sources"]):
        if not name:
            continue
        index[name.lower()] = {
            "canonical": name,
            "match_type": "accepted",
            "synonym_type": "",
            "synonym_sources": "",
            "sources": srcs,
        }

    syn = long_df[long_df["relation"] == "synonym_of"]
    for name, parent, syn_type, srcs in zip(
        syn["synonym_name"], syn["accepted_name"],
        syn["synonym_type_consensus"], syn["sources"],
    ):
        if not name:
            continue
        key = name.lower()
        if index.get(key, {}).get("match_type") == "accepted":
            # Accepted wins over synonym on collision — don't overwrite.
            continue
        index[key] = {
            "canonical": parent,
            "match_type": "synonym",
            "synonym_type": syn_type or "Unknown",
            "synonym_sources": (srcs or "").replace("|", ", "),
            "sources": srcs,
        }

    for name in contested["binomial"].unique():
        if not name:
            continue
        index[name.lower()] = {
            "canonical": name,
            "match_type": "contested",
            "synonym_type": "",
            "synonym_sources": "",
            "sources": "",
        }

    return index


@st.cache_resource(show_spinner=False)
def _accepted_row_sources() -> dict[str, str]:
    """accepted binomial → the `sources` cell of its long-table accepted row."""
    accepted = load_long()
    accepted = accepted[accepted["relation"] == "accepted"]
    return dict(zip(accepted["accepted_name"], accepted["sources"]))


@st.cache_resource(show_spinner=False)
def _contested_rows_by_binomial() -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for rec in load_contested().to_dict("records"):
        grouped.setdefault(rec["binomial"], []).append(rec)
    return grouped


@st.cache_resource(show_spinner=False)
def _species_meta() -> dict[str, dict]:
    """accepted binomial → the handful of wide-table fields the exports need."""
    wide = load_consolidated()
    cols = ["accepted_name", "accepted_authority", "description_year",
            "cites_appendix", "family", "genus"]
    cols = [c for c in cols if c in wide.columns]
    return {r["accepted_name"]: r for r in wide[cols].to_dict("records")}


# --------------------------------------------------------------------------
# Per-source resolution
# --------------------------------------------------------------------------

@dataclass
class SourceVerdict:
    """What one source says about one name."""
    status: str = STATUS_ABSENT
    accepted_name: str = ""   # the name this source treats as current
    detail: str = ""          # free text: synonym type, conflict note, …

    def as_cell(self) -> str:
        if self.status == STATUS_ABSENT:
            return ""
        if self.status == STATUS_ACCEPTED:
            return "accepted"
        if self.status == STATUS_SYNONYM:
            return f"synonym of {self.accepted_name}" if self.accepted_name else "synonym"
        return self.detail or self.status


@dataclass
class Resolution:
    """The full picture for one queried name."""
    query: str
    binomial: str = ""
    verdict: str = "missing"          # accepted | synonym | contested | missing | unparseable
    accepted_name: str = ""           # consolidated accepted name, when there is one
    synonym_type: str = ""
    description_year: str = ""
    cites_appendix: str = ""
    contest_class: str = ""
    contest_reason: str = ""
    note: str = ""
    per_source: dict[str, SourceVerdict] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.per_source is None:
            self.per_source = {}


def resolve(query: str, index: dict[str, dict] | None = None) -> Resolution:
    """Resolve one name against every source.

    This is the single place that decides what a name means, so the species
    card, the batch diff and the CSV export can never drift apart.
    """
    index = index if index is not None else build_search_index()
    normalized = normalize_query(query)
    if not normalized:
        # Still emit an empty verdict per source: the export must stay
        # rectangular whatever the input row looked like.
        return Resolution(
            query=query,
            verdict="unparseable",
            note="fewer than 2 tokens or empty",
            per_source={source: SourceVerdict() for source in SOURCES},
        )

    res = Resolution(query=query, binomial=normalized)
    entry = index.get(normalized.lower())
    meta = _species_meta()

    if entry is None:
        res.verdict = "missing"
        res.note = "no source in this build records this binomial"
        for source in SOURCES:
            res.per_source[source] = SourceVerdict()
        return res

    match_type = entry["match_type"]

    if match_type == "contested":
        res.verdict = "contested"
        rows = _contested_rows_by_binomial().get(normalized, [])
        if rows:
            res.contest_class = rows[0].get("contest_class", "")
            res.contest_reason = rows[0].get("contest_reason", "")
        res.note = res.contest_reason
        for source in SOURCES:
            res.per_source[source] = SourceVerdict()
        for row in rows:
            source = row["source"]
            relation = row.get("source_says_relation", "")
            parent = (row.get("source_says_accepted_parent", "") or "").split("|")[0]
            if relation.startswith("accepted") and "synonym" not in relation:
                res.per_source[source] = SourceVerdict(
                    status=STATUS_ACCEPTED, accepted_name=normalized,
                    detail=row.get("evidence", ""))
            elif relation == "accepted+synonym_of":
                res.per_source[source] = SourceVerdict(
                    status=STATUS_CONTESTED, accepted_name=parent,
                    detail=f"accepted, and also a synonym of {parent}")
            else:
                res.per_source[source] = SourceVerdict(
                    status=STATUS_SYNONYM, accepted_name=parent,
                    detail=row.get("synonym_type", ""))
        # Where a source has no row at all, it simply does not know the name.
        return res

    if match_type == "synonym":
        res.verdict = "synonym"
        res.accepted_name = entry["canonical"]
        res.synonym_type = entry.get("synonym_type", "")
        parent_row = meta.get(res.accepted_name, {})
        res.description_year = parent_row.get("description_year", "")
        res.cites_appendix = parent_row.get("cites_appendix", "")
        pair_sources = split_source_list(entry.get("sources", ""))
        parent_sources = split_source_list(_accepted_row_sources().get(res.accepted_name, ""))
        for source in SOURCES:
            if source in pair_sources:
                res.per_source[source] = SourceVerdict(
                    status=STATUS_SYNONYM, accepted_name=res.accepted_name,
                    detail=res.synonym_type)
            elif source in parent_sources:
                # The source knows the accepted species but not this synonym.
                res.per_source[source] = SourceVerdict(
                    status=STATUS_ABSENT, accepted_name="",
                    detail=f"knows {res.accepted_name}, not this name")
            else:
                res.per_source[source] = SourceVerdict()
        return res

    # accepted
    res.verdict = "accepted"
    res.accepted_name = entry["canonical"]
    row = meta.get(res.accepted_name, {})
    res.description_year = row.get("description_year", "")
    res.cites_appendix = row.get("cites_appendix", "")
    own_sources = split_source_list(entry.get("sources", ""))
    for source in SOURCES:
        if source in own_sources:
            res.per_source[source] = SourceVerdict(
                status=STATUS_ACCEPTED, accepted_name=res.accepted_name)
        else:
            res.per_source[source] = SourceVerdict()
    return res


def per_source_columns(res: Resolution, extra_backbones: dict | None = None) -> dict[str, str]:
    """Flatten a Resolution into the `<source>_status` / `<source>_name` columns
    the batch export carries — one pair per source, in pipeline order."""
    out: dict[str, str] = {}
    for source in SOURCES:
        verdict = res.per_source.get(source, SourceVerdict())
        out[f"{source}_status"] = verdict.status
        out[f"{source}_accepted_name"] = verdict.accepted_name
    for backbone_id, verdict in (extra_backbones or {}).items():
        out[f"{backbone_id}_status"] = verdict.status
        out[f"{backbone_id}_accepted_name"] = verdict.accepted_name
    return out


# --------------------------------------------------------------------------
# Query helpers
# --------------------------------------------------------------------------

def normalize_query(q: str) -> str:
    """Turn a user-typed query into a canonical binomial.

    Handles: extra whitespace, authority tails ('Dracula chimaera (Rchb.f.) Luer'),
    full scientific names, stray capitalization, and the ligature codepoints that
    come out of PDF text layers ('divitiﬂora' → 'divitiflora').
    Returns '' if fewer than 2 tokens.
    """
    q = norm_text(q)
    if not q:
        return ""
    tokens = q.split()
    if len(tokens) < 2:
        return ""
    return make_binomial(tokens[0], tokens[1])


def prefix_matches(query: str, index: dict[str, dict], limit: int = 15) -> list[str]:
    """Return the top-N canonical names whose lowercased binomial starts with
    the query. Falls back to 'contains' matches if prefix yields <limit."""
    q = norm_text(query).lower()
    if not q:
        return []
    starts = []
    contains = []
    for key, val in index.items():
        if key.startswith(q):
            starts.append(val["canonical"])
        elif q in key:
            contains.append(val["canonical"])
        if len(starts) >= limit:
            break
    if len(starts) >= limit:
        return starts[:limit]
    seen: set[str] = set()
    out: list[str] = []
    for n in starts + contains:
        if n in seen:
            continue
        seen.add(n)
        out.append(n)
        if len(out) >= limit:
            break
    return out


def get_species_row(canonical_name: str) -> pd.Series | None:
    """Fetch the wide row for a canonical accepted name."""
    wide = load_consolidated()
    hits = wide[wide["accepted_name"] == canonical_name]
    if hits.empty:
        return None
    return hits.iloc[0]


def get_contested_detail(binomial: str) -> pd.DataFrame:
    """Return the contested-names rows for a binomial (one row per source)."""
    contested = load_contested()
    return contested[contested["binomial"] == binomial].copy()


def parse_synonyms_detailed(detail: str) -> list[dict]:
    """Parse the 'synonyms_detailed' field into structured rows.

    Format: 'Name [Type; src1,src2], Other [Type; src]'.
    """
    if not detail:
        return []
    rows: list[dict] = []
    parts = detail.split("], ")
    for i, p in enumerate(parts):
        if not p:
            continue
        if i < len(parts) - 1:
            p = p + "]"
        lb = p.rfind(" [")
        if lb < 0 or not p.endswith("]"):
            rows.append({"name": p, "type": "", "sources": ""})
            continue
        name = p[:lb].strip()
        meta = p[lb + 2 : -1]
        if ";" in meta:
            typ, src = meta.split(";", 1)
            rows.append({"name": name, "type": typ.strip(), "sources": src.strip()})
        else:
            rows.append({"name": name, "type": meta.strip(), "sources": ""})
    return rows
