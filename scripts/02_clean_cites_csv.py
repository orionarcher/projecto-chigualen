"""Clean the CITES species listings CSV into the uniform schema.

Filters to Orchidaceae, reshapes to the SCHEMA defined in scripts/_normalize.py,
and writes the result to Chigualen/data/clean/cites_csv.csv.

Every row is treated as an accepted-name listing (CITES CSV carries no
synonym information). Rows without a valid binomial (e.g. genus-only
listings with blank species) are dropped.

Run from the project root:
    python3 scripts/02_clean_cites_csv.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

# Make scripts/ importable when run from the project root.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _normalize import (  # noqa: E402
    SCHEMA,
    blank_row,
    binomial,
    norm_text,
    pack_extras,
    strip_hybrid,
    validate_frame,
)

PROJECT_ROOT = SCRIPT_DIR.parent
INPUT_PATH = PROJECT_ROOT / "Chigualen" / "data" / "raw" / "cites_listings.csv"
OUTPUT_PATH = PROJECT_ROOT / "Chigualen" / "data" / "clean" / "cites_csv.csv"


def main() -> None:
    df = pd.read_csv(INPUT_PATH, dtype=str, keep_default_na=False)
    total_rows = len(df)
    print(f"loaded {total_rows} rows from {INPUT_PATH.relative_to(PROJECT_ROOT)}")

    orchids = df[df["Family"] == "Orchidaceae"].copy()
    print(f"rows after Family == 'Orchidaceae': {len(orchids)}")

    dropped_no_binomial = 0
    out_rows: list[dict[str, str]] = []

    for row in orchids.itertuples(index=False):
        r = row._asdict()

        genus = norm_text(r.get("Genus", ""))
        species = norm_text(r.get("Species", ""))
        accepted = strip_hybrid(binomial(genus, species))
        if not accepted:
            dropped_no_binomial += 1
            continue

        author = norm_text(r.get("Author", ""))
        sci_name = strip_hybrid(norm_text(r.get("Scientific Name", "")))
        if sci_name:
            accepted_full = sci_name
        else:
            accepted_full = f"{accepted} {author}".strip()

        extras = {
            "Listed under": norm_text(r.get("Listed under", "")),
            "Party": norm_text(r.get("Party", "")),
            "All_DistributionISOCodes": norm_text(r.get("All_DistributionISOCodes", "")),
            "NativeDistributionFullNames": norm_text(r.get("NativeDistributionFullNames", "")),
            "Introduced_Distribution": norm_text(r.get("Introduced_Distribution", "")),
            "Introduced(?)_Distribution": norm_text(r.get("Introduced(?)_Distribution", "")),
            "Reintroduced_Distribution": norm_text(r.get("Reintroduced_Distribution", "")),
            "Extinct_Distribution": norm_text(r.get("Extinct_Distribution", "")),
            "Extinct(?)_Distribution": norm_text(r.get("Extinct(?)_Distribution", "")),
            "Distribution_Uncertain": norm_text(r.get("Distribution_Uncertain", "")),
            "cites_full_note_num": norm_text(r.get("# Full note", "")),
        }

        out = blank_row()
        out["source"] = "cites_csv"
        out["source_record_id"] = norm_text(r.get("Id", ""))
        out["relation"] = "accepted"
        out["accepted_name"] = accepted
        out["accepted_name_full"] = accepted_full
        out["accepted_authority"] = author
        out["family"] = "Orchidaceae"
        out["genus"] = genus
        out["species"] = norm_text(r.get("Species", ""))
        out["infraspecific_epithet"] = norm_text(r.get("Subspecies", ""))
        out["taxon_rank"] = norm_text(r.get("Rank", ""))
        out["cites_appendix"] = norm_text(r.get("Listing", ""))
        out["cites_full_note"] = norm_text(r.get("Full note", ""))
        out["geographic_area"] = norm_text(r.get("All_DistributionFullNames", ""))
        out["raw_extras"] = pack_extras(extras)
        out_rows.append(out)

    print(f"rows dropped (no binomial possible): {dropped_no_binomial}")

    out_df = pd.DataFrame(out_rows, columns=SCHEMA)

    appendix_counts = out_df["cites_appendix"].value_counts(dropna=False).to_dict()
    print("cites_appendix breakdown:")
    for key in ("I", "II", "III", ""):
        label = key if key else "(blank)"
        print(f"  {label}: {appendix_counts.get(key, 0)}")
    # Surface any unexpected values too.
    for key, val in appendix_counts.items():
        if key not in {"I", "II", "III", ""}:
            print(f"  {key!r}: {val}")

    validate_frame(out_df)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(OUTPUT_PATH, index=False)
    rel = OUTPUT_PATH.relative_to(PROJECT_ROOT)
    print(f"wrote {len(out_df)} rows to {rel}")


if __name__ == "__main__":
    main()
