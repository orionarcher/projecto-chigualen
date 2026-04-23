"""Clean Kew WCVP orchid dataset into the uniform Chigualen schema.

Reads the full WCVP checklist from Chigualen/data/raw/wcvp/wcvp_names.csv
(pipe-delimited, from Kew's sftp.kew.org distribution). The schema-level
distinction is that the full file has a `homotypic_synonym` column carrying
'T' when a Synonym row is a homotypic synonym; absence of T means heterotypic.

Writes Chigualen/data/clean/wcvp.csv.

Run from project root:
    python3 scripts/01_clean_wcvp.py
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pandas as pd

# Make sibling _normalize importable regardless of invocation cwd.
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from _normalize import (  # noqa: E402
    SCHEMA,
    blank_row,
    norm_text,
    binomial,
    strip_hybrid,
    pack_extras,
    validate_frame,
)

PROJECT_ROOT = SCRIPT_DIR.parent
INPUT_PATH = PROJECT_ROOT / "Chigualen" / "data" / "raw" / "wcvp" / "wcvp_names.csv"
OUTPUT_PATH = PROJECT_ROOT / "Chigualen" / "data" / "clean" / "wcvp.csv"

# Map source taxon_status -> (relation, default synonym_type).
# 'Synonym' is special: homotypic_synonym=='T' → Homotypic, else Heterotypic.
STATUS_MAP: dict[str, tuple[str, str]] = {
    "Accepted": ("accepted", ""),
    "Synonym": ("synonym_of", "Heterotypic"),  # overridden by homotypic_synonym=='T'
    "Homotypic_Synonym": ("synonym_of", "Homotypic"),
    "Homotypic Synonym": ("synonym_of", "Homotypic"),
    "Heterotypic_Synonym": ("synonym_of", "Heterotypic"),
    "Heterotypic Synonym": ("synonym_of", "Heterotypic"),
    "Orthographic": ("synonym_of", "Orthographic variant"),
    "Orthographic_Variant": ("synonym_of", "Orthographic variant"),
    "Illegitimate": ("synonym_of", "Nomenclatural"),
    "Invalid": ("synonym_of", "Nomenclatural"),
    "Misapplied": ("synonym_of", "Unknown"),
    "Artificial Hybrid": ("accepted", ""),
    "Unplaced": ("synonym_of", "Unknown"),
}


def build_authority(row: pd.Series) -> str:
    """Prefer taxon_authors; fall back to composing from author fields."""
    authors = norm_text(row.get("taxon_authors"))
    if authors:
        return authors
    parts = []
    p = norm_text(row.get("parenthetical_author"))
    if p:
        parts.append(f"({p})")
    pa = norm_text(row.get("primary_author"))
    if pa:
        parts.append(pa)
    pub = norm_text(row.get("publication_author"))
    if pub:
        parts.append(f"ex {pub}")
    return " ".join(parts).strip()


def build_full_name(taxon_name: str, authors: str) -> str:
    name = norm_text(taxon_name)
    auth = norm_text(authors)
    if name and auth:
        return f"{name} {auth}"
    return name


def main() -> None:
    print(f"reading {INPUT_PATH.relative_to(PROJECT_ROOT)}")
    # WCVP uses literal 'NA' strings for nulls. Keep plant_name_id as string
    # so lookups by id are unambiguous.
    df = pd.read_csv(
        INPUT_PATH,
        sep="|",
        low_memory=False,
        na_values=["NA"],
        keep_default_na=True,
        dtype={
            "plant_name_id": "string",
            "accepted_plant_name_id": "string",
            "basionym_plant_name_id": "string",
            "parent_plant_name_id": "string",
            "ipni_id": "string",
            "homotypic_synonym": "string",
        },
    )
    print(f"total input rows: {len(df)}")

    # Filter to orchids (verify; source is pre-filtered).
    before_filter = len(df)
    df = df[df["family"] == "Orchidaceae"].copy()
    print(f"orchid rows after family filter: {len(df)} (dropped {before_filter - len(df)})")

    # The raw CSV has one row per (plant_name_id, locality). Collapse to one
    # row per plant_name_id, aggregating geographic_area descriptors.
    df["geographic_area"] = df["geographic_area"].fillna("")
    geo_by_id = (
        df.groupby("plant_name_id")["geographic_area"]
        .apply(lambda s: "; ".join(sorted({norm_text(x) for x in s if norm_text(x)})))
    )
    df = df.drop_duplicates(subset=["plant_name_id"]).copy()
    df["geographic_area"] = df["plant_name_id"].map(geo_by_id).fillna("")
    print(f"unique taxa (deduped by plant_name_id): {len(df)}")

    # Enumerate taxon_status vocabulary.
    status_counts = df["taxon_status"].fillna("<missing>").value_counts()
    print("\ntaxon_status distinct values (with counts):")
    for status, n in status_counts.items():
        print(f"  {status!r}: {n}")

    # Warn on unexpected statuses.
    unexpected_statuses: Counter[str] = Counter()
    for status, n in status_counts.items():
        if status == "<missing>":
            unexpected_statuses[status] = n
            print(f"  WARNING: missing taxon_status for {n} rows; treating as Unknown synonym")
        elif status not in STATUS_MAP:
            unexpected_statuses[status] = n
            print(f"  WARNING: unexpected taxon_status {status!r} ({n} rows); mapping to synonym_of/Unknown and preserving raw")

    # Build plant_name_id -> row lookup for accepted-parent resolution.
    # We need genus, species, taxon_name, taxon_authors, and for composing
    # authority the author fields.
    id_lookup: dict[str, dict[str, str]] = {}
    for _, r in df.iterrows():
        pid = norm_text(r.get("plant_name_id"))
        if not pid:
            continue
        id_lookup[pid] = {
            "genus": norm_text(r.get("genus")),
            "species": norm_text(r.get("species")),
            "genus_hybrid": norm_text(r.get("genus_hybrid")),
            "species_hybrid": norm_text(r.get("species_hybrid")),
            "taxon_name": norm_text(r.get("taxon_name")),
            "taxon_authors": norm_text(r.get("taxon_authors")),
            "parenthetical_author": norm_text(r.get("parenthetical_author")),
            "primary_author": norm_text(r.get("primary_author")),
            "publication_author": norm_text(r.get("publication_author")),
        }

    out_rows: list[dict[str, str]] = []
    dropped_bad_binomial = 0
    failed_parent_lookup = 0
    accepted_count = 0
    synonym_count = 0

    for _, r in df.iterrows():
        pid = norm_text(r.get("plant_name_id"))
        raw_status = r.get("taxon_status")
        status_key = norm_text(raw_status) if pd.notna(raw_status) else ""

        if status_key in STATUS_MAP:
            relation, syn_type = STATUS_MAP[status_key]
            status_was_unexpected = False
        else:
            relation, syn_type = ("synonym_of", "Unknown")
            status_was_unexpected = True

        # WCVP encodes homotypic-vs-heterotypic via the homotypic_synonym column
        # ('T' for homotypic, blank otherwise). The default syn_type for
        # status=='Synonym' is Heterotypic; flip to Homotypic when flagged.
        if status_key == "Synonym":
            if norm_text(r.get("homotypic_synonym")) == "T":
                syn_type = "Homotypic"
            else:
                syn_type = "Heterotypic"

        genus_val = norm_text(r.get("genus"))
        species_val = norm_text(r.get("species"))
        genus_hybrid_flag = bool(norm_text(r.get("genus_hybrid")))
        species_hybrid_flag = bool(norm_text(r.get("species_hybrid")))
        is_hybrid = genus_hybrid_flag or species_hybrid_flag

        # Build this row's binomial (and strip any hybrid marker).
        this_binom = binomial(genus_val, species_val)
        if is_hybrid:
            this_binom = strip_hybrid(this_binom)

        # Drop rows without a proper binomial (genus-only entries, etc.).
        if not this_binom:
            dropped_bad_binomial += 1
            continue

        this_authors = build_authority(r)
        this_taxon_name = norm_text(r.get("taxon_name"))
        this_full = build_full_name(this_taxon_name, this_authors)

        accepted_id = norm_text(r.get("accepted_plant_name_id"))

        # Resolve accepted parent.
        if relation == "accepted":
            parent_binom = this_binom
            parent_full = this_full
            parent_authority = this_authors
        else:
            parent = id_lookup.get(accepted_id) if accepted_id else None
            if parent is None:
                failed_parent_lookup += 1
                print(
                    f"  WARNING: plant_name_id={pid} status={status_key!r} "
                    f"accepted_plant_name_id={accepted_id!r} could not be resolved; "
                    f"falling back to self binomial"
                )
                parent_binom = this_binom
                parent_full = this_full
                parent_authority = this_authors
            else:
                pb = binomial(parent["genus"], parent["species"])
                if parent["genus_hybrid"] or parent["species_hybrid"]:
                    pb = strip_hybrid(pb)
                if not pb:
                    # Parent exists but has no binomial — treat as unresolved.
                    failed_parent_lookup += 1
                    print(
                        f"  WARNING: plant_name_id={pid} parent {accepted_id!r} "
                        f"has no binomial; falling back to self"
                    )
                    parent_binom = this_binom
                    parent_full = this_full
                    parent_authority = this_authors
                else:
                    parent_binom = pb
                    # Compose parent authority; prefer taxon_authors.
                    pa = parent["taxon_authors"]
                    if not pa:
                        bits = []
                        if parent["parenthetical_author"]:
                            bits.append(f"({parent['parenthetical_author']})")
                        if parent["primary_author"]:
                            bits.append(parent["primary_author"])
                        if parent["publication_author"]:
                            bits.append(f"ex {parent['publication_author']}")
                        pa = " ".join(bits).strip()
                    parent_authority = pa
                    parent_full = build_full_name(parent["taxon_name"], pa)

        # Build extras.
        extras: dict[str, object] = {}
        lifeform = norm_text(r.get("lifeform_description"))
        if lifeform:
            extras["lifeform_description"] = lifeform
        climate = norm_text(r.get("climate_description"))
        if climate:
            extras["climate_description"] = climate
        if is_hybrid:
            extras["hybrid"] = True
        nomrem = norm_text(r.get("nomenclatural_remarks"))
        if nomrem:
            extras["nomenclatural_remarks"] = nomrem
        volpage = norm_text(r.get("volume_and_page"))
        if volpage:
            extras["volume_and_page"] = volpage
        if status_was_unexpected:
            extras["wcvp_taxon_status_raw"] = status_key or "<missing>"

        row = blank_row()
        row["source"] = "wcvp"
        row["source_record_id"] = pid
        row["relation"] = relation
        row["accepted_name"] = parent_binom
        row["accepted_name_full"] = parent_full
        row["accepted_authority"] = parent_authority

        if relation == "synonym_of":
            row["synonym_name"] = this_binom
            row["synonym_name_full"] = this_full
            row["synonym_authority"] = this_authors
            row["synonym_type"] = syn_type
            synonym_count += 1
        else:
            accepted_count += 1

        row["family"] = "Orchidaceae"
        row["genus"] = genus_val
        row["species"] = species_val
        row["infraspecific_rank"] = norm_text(r.get("infraspecific_rank"))
        row["infraspecific_epithet"] = norm_text(r.get("infraspecies"))
        row["taxon_rank"] = norm_text(r.get("taxon_rank"))
        row["basionym"] = norm_text(r.get("basionym_plant_name_id"))
        row["wcvp_plant_name_id"] = pid
        row["wcvp_accepted_plant_name_id"] = accepted_id
        row["wcvp_ipni_id"] = norm_text(r.get("ipni_id"))
        # wfo_taxon_id, cites_appendix, cites_full_note left blank.
        row["geographic_area"] = norm_text(r.get("geographic_area"))
        row["first_published"] = norm_text(r.get("first_published"))
        row["place_of_publication"] = norm_text(r.get("place_of_publication"))
        row["raw_extras"] = pack_extras(extras)

        out_rows.append(row)

    out_df = pd.DataFrame(out_rows, columns=SCHEMA)

    print()
    print(f"accepted rows: {accepted_count}")
    print(f"synonym rows: {synonym_count}")
    print(f"dropped (no binomial): {dropped_bad_binomial}")
    print(f"synonym rows with unresolved accepted parent: {failed_parent_lookup}")

    validate_frame(out_df)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(OUTPUT_PATH, index=False)
    rel_out = OUTPUT_PATH.relative_to(PROJECT_ROOT)
    print(f"wrote {len(out_df)} rows to {rel_out}")


if __name__ == "__main__":
    main()
