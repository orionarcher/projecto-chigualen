"""Cached data loaders and search-index construction for the Chigualen app."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from _normalize import binomial as make_binomial  # noqa: E402
from _normalize import norm_text  # noqa: E402

OUT_DIR = ROOT / "Chigualen" / "data" / "out"

CONSOLIDATED_PATH = OUT_DIR / "orchid_synonyms_consolidated.csv"
LONG_PATH = OUT_DIR / "orchid_synonyms_long.csv"
CONTESTED_PATH = OUT_DIR / "contested_names.csv"


@st.cache_data(show_spinner="Loading consolidated species…")
def load_consolidated() -> pd.DataFrame:
    df = pd.read_csv(CONSOLIDATED_PATH, dtype=str, keep_default_na=False)
    df["synonym_count"] = pd.to_numeric(df["synonym_count"], errors="coerce").fillna(0).astype(int)
    return df


@st.cache_data(show_spinner="Loading synonym pairs…")
def load_long() -> pd.DataFrame:
    return pd.read_csv(LONG_PATH, dtype=str, keep_default_na=False)


@st.cache_data(show_spinner="Loading contested names…")
def load_contested() -> pd.DataFrame:
    return pd.read_csv(CONTESTED_PATH, dtype=str, keep_default_na=False)


@st.cache_data(show_spinner="Building search index…")
def build_search_index() -> dict[str, dict]:
    """key=lowercased binomial → {canonical, match_type, synonym_type, synonym_sources}

    Priority order (later writes win only for non-contested upgrades):
        1. accepted (from wide)
        2. synonym (from long)
        3. contested (from contested_names; always wins — overrides anything else)
    """
    wide = load_consolidated()
    long_df = load_long()
    contested = load_contested()

    index: dict[str, dict] = {}

    # Accepted names
    for name in wide["accepted_name"]:
        if not name:
            continue
        key = name.lower()
        index[key] = {
            "canonical": name,
            "match_type": "accepted",
            "synonym_type": "",
            "synonym_sources": "",
        }

    # Synonyms: long-format rows with relation == 'synonym_of'
    syn = long_df[long_df["relation"] == "synonym_of"]
    for _, r in syn.iterrows():
        syn_name = r["synonym_name"]
        if not syn_name:
            continue
        key = syn_name.lower()
        if key in index and index[key]["match_type"] == "accepted":
            # Accepted wins over synonym on collision — don't overwrite.
            continue
        index[key] = {
            "canonical": r["accepted_name"],
            "match_type": "synonym",
            "synonym_type": r.get("synonym_type_consensus", "") or "Unknown",
            "synonym_sources": (r.get("sources", "") or "").replace("|", ", "),
        }

    # Contested overrides everything
    for name in contested["binomial"].unique():
        if not name:
            continue
        key = name.lower()
        index[key] = {
            "canonical": name,
            "match_type": "contested",
            "synonym_type": "",
            "synonym_sources": "",
        }

    return index


def normalize_query(q: str) -> str:
    """Turn a user-typed query into a canonical binomial.

    Handles: extra whitespace, authority tails ('Dracula chimaera (Rchb.f.) Luer'),
    full scientific names, stray capitalization.
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
    # Dedup and cap
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
    # Split on ', ' but only when followed by something that ends with ']' later.
    # Simpler: split on '], ' and restore the closing bracket.
    parts = detail.split("], ")
    for i, p in enumerate(parts):
        if not p:
            continue
        if i < len(parts) - 1:
            p = p + "]"
        # Find the last '[' to separate name from meta
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
