"""Clean the user-curated orchid synonyms CSV into the uniform schema.

Input:  Chigualen/data/raw/user_synonyms.csv
Output: Chigualen/data/clean/user_synonyms.csv
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pandas as pd

from _normalize import (
    SCHEMA,
    blank_row,
    binomial,
    norm_text,
    pack_extras,
    strip_hybrid,
    validate_frame,
)

# Paths relative to project root (this script is run from there).
INPUT_PATH = Path("Chigualen/data/raw/user_synonyms.csv")
OUTPUT_PATH = Path("Chigualen/data/clean/user_synonyms.csv")

STATUS_MAP = {
    "Homotypic_Synonym": "Homotypic",
    "Heterotypic_Synonym": "Heterotypic",
}


def split_name(raw: str) -> tuple[str, str, str]:
    """Return (genus, species, full_if_infraspecific_else_empty).

    `full_if_infraspecific_else_empty` is the normalized full string when the
    input has more than two whitespace-separated tokens, otherwise ''.
    """
    normalized = norm_text(raw)
    if not normalized:
        return "", "", ""
    tokens = normalized.split()
    if len(tokens) < 2:
        return "", "", ""
    genus, species = tokens[0], tokens[1]
    extra = normalized if len(tokens) > 2 else ""
    return genus, species, extra


def main() -> None:
    df_in = pd.read_csv(INPUT_PATH, index_col=0)
    print(f"input row count: {len(df_in)}")

    status_counts = Counter(df_in["status"].astype(str).tolist())
    print("distinct status values:")
    for status, count in status_counts.most_common():
        print(f"  {status!r}: {count}")

    unknown_statuses = [s for s in status_counts if s not in STATUS_MAP]
    if unknown_statuses:
        print(
            "!!! WARNING: unexpected status values mapped to 'Unknown': "
            f"{unknown_statuses}"
        )

    rows: list[dict[str, str]] = []
    synonym_type_counter: Counter[str] = Counter()
    dropped_row_numbers: list[int] = []
    infraspecific_count = 0

    for pos, (_, record) in enumerate(df_in.iterrows()):
        accepted_raw = norm_text(record.get("accepted_name"))
        synonym_raw = norm_text(record.get("synonym_name"))
        status_raw = norm_text(record.get("status"))

        acc_genus, acc_species, acc_full_extra = split_name(accepted_raw)
        syn_genus, syn_species, syn_full_extra = split_name(synonym_raw)

        accepted_binom = strip_hybrid(binomial(acc_genus, acc_species))
        synonym_binom = strip_hybrid(binomial(syn_genus, syn_species))

        if not accepted_binom or not synonym_binom:
            dropped_row_numbers.append(pos)
            continue

        # Synonym type mapping.
        if status_raw in STATUS_MAP:
            syn_type = STATUS_MAP[status_raw]
        else:
            syn_type = "Unknown"

        # raw_extras: stash infraspecifics + unknown status literal.
        extras: dict[str, str] = {}
        if acc_full_extra:
            extras["accepted_name_full_raw"] = acc_full_extra
        if syn_full_extra:
            extras["synonym_name_full_raw"] = syn_full_extra
        if acc_full_extra or syn_full_extra:
            infraspecific_count += 1
        if status_raw not in STATUS_MAP:
            extras["user_synonym_status_raw"] = status_raw

        # Parse out synonym-side genus/species for the flat taxonomic columns.
        syn_binom_parts = synonym_binom.split()
        synonym_genus = syn_binom_parts[0] if syn_binom_parts else ""
        synonym_species = syn_binom_parts[1] if len(syn_binom_parts) > 1 else ""

        row = blank_row()
        row["source"] = "user_synonyms"
        row["source_record_id"] = str(pos)
        row["relation"] = "synonym_of"
        row["accepted_name"] = accepted_binom
        row["accepted_name_full"] = accepted_raw
        row["accepted_authority"] = ""
        row["synonym_name"] = synonym_binom
        row["synonym_name_full"] = synonym_raw
        row["synonym_authority"] = ""
        row["synonym_type"] = syn_type
        row["family"] = "Orchidaceae"
        row["genus"] = synonym_genus
        row["species"] = synonym_species
        row["raw_extras"] = pack_extras(extras)

        rows.append(row)
        synonym_type_counter[syn_type] += 1

    print("rows by synonym_type:")
    for st, count in synonym_type_counter.most_common():
        print(f"  {st}: {count}")

    print(f"rows dropped (bad binomial): {len(dropped_row_numbers)}")
    if dropped_row_numbers:
        print(f"  offending row numbers: {dropped_row_numbers}")

    print(f"rows with infraspecific info stashed in raw_extras: {infraspecific_count}")

    df_out = pd.DataFrame(rows, columns=SCHEMA)
    validate_frame(df_out)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_csv(OUTPUT_PATH, index=False)
    print(f"wrote {len(df_out)} rows to {OUTPUT_PATH.as_posix()}")


if __name__ == "__main__":
    main()
