"""Pivot the long consolidated output into wide, species-per-row form.

Reads  data/out/orchid_synonyms_long.csv
Writes data/out/orchid_synonyms_consolidated.csv  (primary — wide default)
       data/out/unique_to_one_source.csv          (wide, filtered to single-source)

Column order places `sources` second so it's visible at a glance. List-valued
cells use COMMAS (quoted by CSV), per project convention. The `synonyms` column
is a plain comma-separated list of synonym binomials; `synonyms_detailed`
carries the per-synonym type and sources alongside each name.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "Chigualen" / "data" / "out"
CONTESTED_PATH = OUT / "contested_names.csv"

SEP = ", "  # intra-cell list separator; CSV quoting handles the commas


# Column order for the wide output. `sources` second on purpose.
WIDE_COLS = [
    "accepted_name",
    "sources",
    "synonym_count",
    "synonyms",
    "synonyms_detailed",
    "contested_synonym_count",
    "contested_synonyms",
    "accepted_name_full",
    "accepted_authority",
    "family",
    "genus",
    "species",
    "taxon_rank",
    "description_year",
    "cites_appendix",
    "cites_full_note",
    "wcvp_plant_name_id",
    "wcvp_ipni_id",
    "wfo_taxon_id",
    "basionym",
    "first_published",
    "place_of_publication",
    "geographic_area",
    "classification",
    "unique_to_source",
    "raw_extras",
]


def join_unique(seq) -> str:
    """Comma-join preserving order, dropping blanks and duplicates."""
    seen: set[str] = set()
    out: list[str] = []
    for x in seq:
        if not x:
            continue
        for piece in str(x).split("|"):
            piece = piece.strip()
            if piece and piece not in seen:
                seen.add(piece)
                out.append(piece)
    return SEP.join(out)


def contested_links(df_contested: pd.DataFrame) -> dict[str, str]:
    """Map accepted species → the contested names that at least one source
    places under it.

    Contested binomials are held out of the consolidated table on purpose: the
    sources cannot agree on them. But dropping them silently made a species look
    as though nobody had ever proposed the name — searching *Stelis ariasii*
    gave no hint that *Anathallis ariasii* is the same plant under a name CITES
    still lists as accepted. Surfacing the link keeps the species card honest
    without promoting a disputed name to a settled synonym.
    """
    if df_contested.empty:
        return {}
    claims = df_contested[
        (df_contested["source_says_relation"] == "synonym_of")
        & (df_contested["source_says_accepted_parent"] != "")
    ]
    by_parent: dict[str, list[str]] = {}
    for _, r in claims.iterrows():
        for parent in str(r["source_says_accepted_parent"]).split("|"):
            parent = parent.strip()
            if not parent:
                continue
            names = by_parent.setdefault(parent, [])
            if r["binomial"] not in names:
                names.append(r["binomial"])
    return {parent: SEP.join(sorted(names)) for parent, names in by_parent.items()}


def pivot(df_long: pd.DataFrame, contested_by_parent: dict[str, str] | None = None) -> pd.DataFrame:
    accepted = df_long[df_long["relation"] == "accepted"].copy()
    synonyms = df_long[df_long["relation"] == "synonym_of"].copy()

    # ---- per-species synonym aggregates ----
    syn_groups = synonyms.groupby("accepted_name")

    def build_detailed(g: pd.DataFrame) -> str:
        parts: list[str] = []
        for _, r in g.iterrows():
            name = r["synonym_name"]
            typ = r.get("synonym_type_consensus") or "Unknown"
            srcs = (r.get("sources") or "").replace("|", ",")
            parts.append(f"{name} [{typ}; {srcs}]")
        return SEP.join(parts)

    syn_names = syn_groups["synonym_name"].apply(
        lambda s: SEP.join(sorted(set(x for x in s if x)))
    )
    syn_counts = syn_groups.size()
    syn_detailed = syn_groups.apply(build_detailed)

    # ---- per-species combined source list (species + all its synonyms) ----
    # Start with the sources mentioning the accepted row, then union in the
    # sources of every synonym that maps to it.
    acc_sources_by_name = accepted.set_index("accepted_name")["sources"]

    def all_sources_for(name: str) -> str:
        bits: list[str] = []
        acc_src = acc_sources_by_name.get(name, "")
        if acc_src:
            bits.append(acc_src)
        if name in syn_groups.groups:
            for src in syn_groups.get_group(name)["sources"]:
                if src:
                    bits.append(src)
        return join_unique(bits)

    # ---- build wide frame ----
    wide = accepted.set_index("accepted_name").copy()
    wide["synonym_count"] = wide.index.map(lambda n: int(syn_counts.get(n, 0)))
    wide["synonyms"] = wide.index.map(lambda n: syn_names.get(n, ""))
    wide["synonyms_detailed"] = wide.index.map(lambda n: syn_detailed.get(n, ""))
    wide["sources"] = wide.index.map(all_sources_for)

    links = contested_by_parent or {}
    wide["contested_synonyms"] = wide.index.map(lambda n: links.get(n, ""))
    wide["contested_synonym_count"] = wide["contested_synonyms"].map(
        lambda v: len(v.split(SEP)) if v else 0
    )
    wide = wide.reset_index()

    # unique_to_source from the accepted row carries species-scope uniqueness;
    # if the species has synonyms, it's only truly unique when every synonym is
    # ALSO from just that one source.
    def effective_unique(row) -> str:
        name = row["accepted_name"]
        species_srcs = set(row["sources"].split(SEP)) if row["sources"] else set()
        species_srcs.discard("")
        return next(iter(species_srcs)) if len(species_srcs) == 1 else ""

    wide["unique_to_source"] = wide.apply(effective_unique, axis=1)

    # Ensure every WIDE_COLS column exists (some may be missing if the long
    # table is narrow — defensive, should not trigger in practice).
    for col in WIDE_COLS:
        if col not in wide.columns:
            wide[col] = ""

    wide = wide[WIDE_COLS].fillna("")
    return wide


def main() -> int:
    df_long = pd.read_csv(OUT / "orchid_synonyms_long.csv", dtype=str, keep_default_na=False)
    print(f"loaded long: {len(df_long)} rows")

    if CONTESTED_PATH.exists():
        df_contested = pd.read_csv(CONTESTED_PATH, dtype=str, keep_default_na=False)
        print(f"loaded contested: {len(df_contested)} rows")
    else:
        df_contested = pd.DataFrame()
        print("contested_names.csv not found — contested_synonyms will be empty")

    wide = pivot(df_long, contested_links(df_contested))
    print(f"wide: {len(wide)} species-level rows")
    print(f"  with >=1 synonym: {(wide['synonym_count'].astype(int) > 0).sum()}")
    print(f"  with 0 synonyms:  {(wide['synonym_count'].astype(int) == 0).sum()}")
    print(f"  with >=1 contested name attached: "
          f"{(wide['contested_synonym_count'].astype(int) > 0).sum()}")
    print(f"  with a description year: {(wide['description_year'] != '').sum()}")

    primary_path = OUT / "orchid_synonyms_consolidated.csv"
    wide.to_csv(primary_path, index=False)
    print(f"wrote {primary_path.relative_to(ROOT)}")

    unique = wide[wide["unique_to_source"] != ""].copy()
    unique_path = OUT / "unique_to_one_source.csv"
    unique.to_csv(unique_path, index=False)
    print(f"wrote {unique_path.relative_to(ROOT)} ({len(unique)} rows)")
    for s in ["wcvp", "wfo", "cites_csv", "cites_pdf", "user_synonyms"]:
        n = (unique["unique_to_source"] == s).sum()
        print(f"  unique to {s}: {n}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
