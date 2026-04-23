"""Shared normalization helpers for every per-source cleaner.

The frozen uniform schema — every data/clean/*.csv must have exactly these
columns in this order.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

SCHEMA: list[str] = [
    "source",
    "source_record_id",
    "relation",
    "accepted_name",
    "accepted_name_full",
    "accepted_authority",
    "synonym_name",
    "synonym_name_full",
    "synonym_authority",
    "synonym_type",
    "family",
    "genus",
    "species",
    "infraspecific_rank",
    "infraspecific_epithet",
    "taxon_rank",
    "basionym",
    "wcvp_plant_name_id",
    "wcvp_accepted_plant_name_id",
    "wcvp_ipni_id",
    "wfo_taxon_id",
    "cites_appendix",
    "cites_full_note",
    "geographic_area",
    "first_published",
    "place_of_publication",
    "raw_extras",
]

VALID_RELATIONS = {"accepted", "synonym_of"}
VALID_SYNONYM_TYPES = {
    "Homotypic",
    "Heterotypic",
    "Nomenclatural",
    "Pro parte",
    "Orthographic variant",
    "Unknown",
    "",
}

_WS = re.compile(r"\s+")


def norm_text(value: Any) -> str:
    """NFC unicode, strip, collapse internal whitespace. None/NaN → ''."""
    if value is None:
        return ""
    s = str(value)
    if s.lower() in {"nan", "none"}:
        return ""
    s = unicodedata.normalize("NFC", s)
    s = _WS.sub(" ", s).strip()
    return s


def binomial(genus: Any, species: Any) -> str:
    """Build 'Genus species' with capitalized genus, lowercase species."""
    g = norm_text(genus)
    s = norm_text(species).lower()
    if not g or not s:
        return ""
    return f"{g[:1].upper()}{g[1:].lower()} {s}"


def strip_hybrid(name: str) -> str:
    """Drop leading/standalone × hybrid markers so joins don't break on them.

    Binomials like '× Aerides houlletiana' and 'Aerides × houlletiana' become
    'Aerides houlletiana'. The hybrid fact is not preserved in v1.
    """
    if not name:
        return ""
    # Remove × (U+00D7) and x-as-hybrid when surrounded by spaces.
    name = re.sub(r"(^|\s)[×x](?=\s)", " ", name)
    return _WS.sub(" ", name).strip()


def pack_extras(extras: dict[str, Any]) -> str:
    """Serialize source-specific columns as JSON for the raw_extras field."""
    clean = {k: v for k, v in extras.items() if v not in (None, "", "nan")}
    if not clean:
        return ""
    return json.dumps(clean, ensure_ascii=False, sort_keys=True, default=str)


def blank_row() -> dict[str, str]:
    """Empty schema-shaped dict. Cleaners fill in what they know."""
    return {col: "" for col in SCHEMA}


def validate_frame(df) -> None:
    """Hard-check a cleaner's output dataframe before writing."""
    missing = set(SCHEMA) - set(df.columns)
    extra = set(df.columns) - set(SCHEMA)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    if extra:
        raise ValueError(f"unexpected columns: {sorted(extra)}")
    bad_rel = set(df["relation"].unique()) - VALID_RELATIONS
    if bad_rel:
        raise ValueError(f"invalid relation values: {bad_rel}")
    bad_syn = set(df["synonym_type"].unique()) - VALID_SYNONYM_TYPES
    if bad_syn:
        raise ValueError(f"invalid synonym_type values: {bad_syn}")
    syn_rows = df[df["relation"] == "synonym_of"]
    if (syn_rows["synonym_name"] == "").any():
        raise ValueError("synonym_of rows must have non-empty synonym_name")
    if (df["accepted_name"] == "").any():
        raise ValueError("every row must have non-empty accepted_name")
