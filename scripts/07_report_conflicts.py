"""Produce summary statistics on the consolidation output.

Writes data/out/conflicts_summary.csv — counts and per-source coverage stats.
Complements the per-row data already in contested_names.csv.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _sources import PIPELINE_ORDER  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CLEAN_DIR = ROOT / "Chigualen" / "data" / "clean"
OUT_DIR = ROOT / "Chigualen" / "data" / "out"

SOURCES = list(PIPELINE_ORDER)


def main() -> int:
    # Output A is the *long* table. `orchid_synonyms_consolidated.csv` is the
    # wide pivot that 08 writes afterwards and has neither `relation` nor
    # `synonym_type_consensus`, so reading it here used to fail outright on a
    # clean run — 07 comes before 08.
    df_a = pd.read_csv(OUT_DIR / "orchid_synonyms_long.csv",
                       dtype=str, keep_default_na=False)
    df_b = pd.read_csv(OUT_DIR / "contested_names.csv",
                       dtype=str, keep_default_na=False)

    rows: list[dict[str, object]] = []

    # ------------------------------------------------------------------
    # Contest counts
    # ------------------------------------------------------------------
    contest_counts = df_b["contest_class"].value_counts().to_dict()
    # binomials (not rows) per contest class
    binomials_per_class = df_b.groupby("contest_class")["binomial"].nunique().to_dict()
    for cls, n in contest_counts.items():
        rows.append({
            "category": "contest_rows",
            "key": cls,
            "count": n,
            "note": f"{binomials_per_class.get(cls, 0)} distinct binomials in this class",
        })

    # ------------------------------------------------------------------
    # Synonym-type disagreements within Output A (where sources agreed on
    # parent but disagreed on homotypic/heterotypic).
    # ------------------------------------------------------------------
    mixed_type = df_a[(df_a["relation"] == "synonym_of") &
                      (df_a["synonym_type_consensus"] == "Mixed")]
    rows.append({
        "category": "synonym_type_disagreement",
        "key": "Mixed (homotypic vs heterotypic across sources)",
        "count": len(mixed_type),
        "note": "See Output A rows where synonym_type_consensus == 'Mixed'",
    })

    unknown_only = df_a[(df_a["relation"] == "synonym_of") &
                        (df_a["synonym_type_consensus"] == "Unknown")]
    rows.append({
        "category": "synonym_type_coverage",
        "key": "Unknown (no source classified)",
        "count": len(unknown_only),
        "note": "Only CITES PDF / WFO / Unplaced sources; user_synonyms classifies.",
    })

    for t in ["Homotypic", "Heterotypic", "Orthographic variant", "Nomenclatural", "Pro parte"]:
        n = (df_a["synonym_type_consensus"] == t).sum()
        if n:
            rows.append({
                "category": "synonym_type_coverage",
                "key": t,
                "count": int(n),
                "note": "",
            })

    # ------------------------------------------------------------------
    # Per-source coverage (from cleaned inputs, not consolidated)
    # ------------------------------------------------------------------
    for source in SOURCES:
        clean_path = CLEAN_DIR / f"{source}.csv"
        if not clean_path.exists():
            # The raw inputs of three sources are not committed, so a checkout
            # can legitimately have only some cleaned files. Report the gap
            # instead of failing the whole summary.
            rows.append({
                "category": "per_source_counts",
                "key": f"{source}.unavailable",
                "count": 0,
                "note": f"{clean_path.relative_to(ROOT)} not present — rebuild this source to include it",
            })
            continue
        df = pd.read_csv(clean_path, dtype=str, keep_default_na=False)
        acc_count = int((df["relation"] == "accepted").sum())
        syn_count = int((df["relation"] == "synonym_of").sum())
        # distinct taxon_status values observed (via raw_extras, captured when
        # vocabulary didn't match the standard set)
        status_vocab: Counter[str] = Counter()
        for blob in df["raw_extras"]:
            if not blob:
                continue
            try:
                data = json.loads(blob)
            except ValueError:
                continue
            for key in ("wcvp_taxon_status_raw", "wfo_taxonomic_status_raw",
                        "user_synonym_status_raw"):
                if key in data:
                    status_vocab[data[key]] += 1

        rows.append({
            "category": "per_source_counts",
            "key": f"{source}.accepted",
            "count": acc_count,
            "note": "",
        })
        rows.append({
            "category": "per_source_counts",
            "key": f"{source}.synonym_of",
            "count": syn_count,
            "note": "",
        })
        for status, n in status_vocab.most_common():
            rows.append({
                "category": "per_source_nonstandard_status",
                "key": f"{source}: {status}",
                "count": n,
                "note": "Raw status value preserved in raw_extras — mapped to Unknown in synonym_type.",
            })

    # ------------------------------------------------------------------
    # Output-A unique-to-one-source breakdown (for completeness)
    # ------------------------------------------------------------------
    for s in SOURCES:
        n = int((df_a["unique_to_source"] == s).sum())
        rows.append({
            "category": "unique_to_one_source",
            "key": s,
            "count": n,
            "note": "Rows in Output A backed by only this source.",
        })

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------
    df_out = pd.DataFrame(rows, columns=["category", "key", "count", "note"])
    path = OUT_DIR / "conflicts_summary.csv"
    df_out.to_csv(path, index=False)
    print(f"wrote {len(df_out)} summary rows to {path.relative_to(ROOT)}")
    print(df_out.to_string(index=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
