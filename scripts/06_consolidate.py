"""Consolidate the five cleaned sources into three outputs.

Output A: data/out/orchid_synonyms_consolidated.csv
    Binomials where no cross-source contradiction exists.
    One row per (accepted, synonym) pair, plus accepted-only rows for names
    with no synonyms recorded anywhere.

Output B: data/out/contested_names.csv
    Binomials where sources disagree on accepted-vs-synonym status or on which
    parent a synonym belongs to. One row per (binomial, source) — NOT collapsed.

Output C: data/out/unique_to_one_source.csv
    Subset of Output A where the row is backed by exactly one source.

Source priority (highest → lowest): wcvp > wfo > cites_csv > cites_pdf > user_synonyms
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _normalize import SCHEMA  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CLEAN_DIR = ROOT / "Chigualen" / "data" / "clean"
OUT_DIR = ROOT / "Chigualen" / "data" / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SOURCES = ["wcvp", "wfo", "cites_csv", "cites_pdf", "user_synonyms"]
PRIORITY = {s: i for i, s in enumerate(SOURCES)}


def load_sources() -> dict[str, pd.DataFrame]:
    frames = {}
    for name in SOURCES:
        df = pd.read_csv(CLEAN_DIR / f"{name}.csv", dtype=str, keep_default_na=False)
        print(f"loaded {name}: {len(df):>6} rows")
        frames[name] = df
    return frames


def pick_best(values_by_source: dict[str, str]) -> str:
    """Return the first non-empty value from the highest-priority source."""
    for s in SOURCES:
        v = values_by_source.get(s, "")
        if v:
            return v
    return ""


def merge_extras(extras_by_source: dict[str, str]) -> str:
    merged: dict[str, object] = {}
    for s in SOURCES:
        raw = extras_by_source.get(s, "")
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue
        for k, v in data.items():
            if k not in merged:
                merged[k] = v
    if not merged:
        return ""
    return json.dumps(merged, ensure_ascii=False, sort_keys=True, default=str)


def main() -> int:
    frames = load_sources()

    # ---------------------------------------------------------------
    # Step 1: build per-source views of what each source says about X
    # ---------------------------------------------------------------
    # accepted_set[source]  = set of binomials this source treats as accepted
    # synonym_of[source]    = dict {X: set(Y)}  where S says X is a synonym of Y
    # rows_by_binomial[binomial][source] = list of full row-dicts that mention it
    accepted_set: dict[str, set[str]] = {s: set() for s in SOURCES}
    synonym_claim: dict[str, dict[str, set[str]]] = {s: defaultdict(set) for s in SOURCES}
    rows_by_binomial: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    # Capture self-synonym (X synonym-of X) separately — these are infraspecific
    # or authority-level synonymy that collapses at the binomial level.
    self_synonym_counts: dict[str, int] = {s: 0 for s in SOURCES}

    for source, df in frames.items():
        for rec in df.to_dict("records"):
            relation = rec["relation"]
            acc = rec["accepted_name"]
            syn = rec["synonym_name"]

            if relation == "accepted":
                accepted_set[source].add(acc)
                rows_by_binomial[acc][source].append(rec)
            elif relation == "synonym_of":
                # The accepted_name field in a synonym row records what the source
                # claims is the current accepted parent — so this source ALSO
                # implicitly considers that parent accepted.
                if acc and acc != syn:
                    accepted_set[source].add(acc)
                if syn == acc or not syn:
                    self_synonym_counts[source] += 1
                    continue
                synonym_claim[source][syn].add(acc)
                rows_by_binomial[syn][source].append(rec)
                # The parent binomial also gets indexed so its metadata can be
                # assembled later, even if no source emits an 'accepted' row for it.
                rows_by_binomial[acc][source].append(rec)

    print("\nper-source accepted binomial counts:")
    for s in SOURCES:
        print(f"  {s}: {len(accepted_set[s]):>6} accepted, "
              f"{len(synonym_claim[s]):>6} distinct synonyms, "
              f"{self_synonym_counts[s]:>5} self-synonyms (dropped)")

    all_binomials = set(rows_by_binomial.keys())
    print(f"\n{len(all_binomials)} distinct binomials observed across all sources")

    # ---------------------------------------------------------------
    # Step 2: classify each binomial
    # ---------------------------------------------------------------
    unambiguous_accepted: set[str] = set()
    unambiguous_synonym: dict[str, str] = {}  # binomial → agreed parent
    contested_status: set[str] = set()
    contested_parent: set[str] = set()

    for x in all_binomials:
        accepted_by = [s for s in SOURCES if x in accepted_set[s]]
        synonym_by: dict[str, set[str]] = {s: synonym_claim[s][x] for s in SOURCES if x in synonym_claim[s]}

        if accepted_by and synonym_by:
            contested_status.add(x)
        elif accepted_by and not synonym_by:
            unambiguous_accepted.add(x)
        elif synonym_by and not accepted_by:
            # Collect all claimed parents across sources
            all_parents: set[str] = set()
            for parents in synonym_by.values():
                all_parents.update(parents)
            if len(all_parents) == 1:
                unambiguous_synonym[x] = next(iter(all_parents))
            else:
                contested_parent.add(x)
        # else: neither accepted nor synonym anywhere — shouldn't happen

    print(f"\nclassification:")
    print(f"  unambiguous_accepted:  {len(unambiguous_accepted):>6}")
    print(f"  unambiguous_synonym:   {len(unambiguous_synonym):>6}")
    print(f"  contested_status:      {len(contested_status):>6}")
    print(f"  contested_parent:      {len(contested_parent):>6}")

    # Names classified as unambiguous_synonym whose parent is itself contested:
    # route them to Output B too, since the parent's ambiguity infects them.
    contested_parents_set = contested_status | contested_parent
    orphaned_by_parent = {x for x, parent in unambiguous_synonym.items()
                          if parent in contested_parents_set}
    if orphaned_by_parent:
        print(f"  (moving {len(orphaned_by_parent)} synonyms to contested because their "
              f"parent is contested)")
        for x in orphaned_by_parent:
            del unambiguous_synonym[x]
        contested_parent.update(orphaned_by_parent)

    # ---------------------------------------------------------------
    # Step 3: build Output A
    # ---------------------------------------------------------------
    def field_by_source(binomial: str, field: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for s in SOURCES:
            for rec in rows_by_binomial[binomial].get(s, []):
                v = rec.get(field, "")
                if v:
                    out.setdefault(s, v)
                    break
        return out

    def merged_union(binomial: str, field: str, sep: str = "; ") -> str:
        seen: set[str] = set()
        out: list[str] = []
        for s in SOURCES:
            for rec in rows_by_binomial[binomial].get(s, []):
                v = rec.get(field, "")
                if not v:
                    continue
                for piece in v.split(sep):
                    piece = piece.strip()
                    if piece and piece not in seen:
                        seen.add(piece)
                        out.append(piece)
        return sep.join(out)

    def sources_that_mention(binomial: str, relation_filter: str | None = None) -> list[str]:
        out: list[str] = []
        for s in SOURCES:
            recs = rows_by_binomial[binomial].get(s, [])
            if not recs:
                continue
            if relation_filter is None:
                out.append(s)
            elif any(r["relation"] == relation_filter for r in recs):
                out.append(s)
        return out

    rows_a: list[dict[str, str]] = []

    # 3a. Accepted-only rows — one per unambiguous_accepted binomial with no
    # synonyms pointing at it. Synonym rows (below) will also pull their
    # accepted parent's metadata, so an accepted binomial with synonyms gets
    # its metadata via the first synonym pair AND also gets a standalone row
    # for discoverability.
    for x in sorted(unambiguous_accepted):
        acc_full_by = field_by_source(x, "accepted_name_full")
        acc_auth_by = field_by_source(x, "accepted_authority")
        genus_by = field_by_source(x, "genus")
        species_by = field_by_source(x, "species")
        family_by = field_by_source(x, "family")
        rank_by = field_by_source(x, "taxon_rank")
        basionym_by = field_by_source(x, "basionym")
        wcvp_id_by = field_by_source(x, "wcvp_plant_name_id")
        wcvp_acc_id_by = field_by_source(x, "wcvp_accepted_plant_name_id")
        wcvp_ipni_by = field_by_source(x, "wcvp_ipni_id")
        wfo_id_by = field_by_source(x, "wfo_taxon_id")
        cites_app_by = field_by_source(x, "cites_appendix")
        cites_note_by = field_by_source(x, "cites_full_note")
        firstpub_by = field_by_source(x, "first_published")
        pop_by = field_by_source(x, "place_of_publication")
        extras_by = {s: rows_by_binomial[x].get(s, [{}])[0].get("raw_extras", "")
                     for s in SOURCES if rows_by_binomial[x].get(s)}

        srcs = sources_that_mention(x)
        row = {col: "" for col in SCHEMA + ["sources", "synonym_types_observed",
                                             "synonym_type_consensus", "unique_to_source",
                                             "classification"]}
        row.update({
            "source": "consolidated",
            "source_record_id": "",
            "relation": "accepted",
            "accepted_name": x,
            "accepted_name_full": pick_best(acc_full_by) or x,
            "accepted_authority": pick_best(acc_auth_by),
            "family": pick_best(family_by) or "Orchidaceae",
            "genus": pick_best(genus_by),
            "species": pick_best(species_by),
            "taxon_rank": pick_best(rank_by),
            "basionym": pick_best(basionym_by),
            "wcvp_plant_name_id": pick_best(wcvp_id_by),
            "wcvp_accepted_plant_name_id": pick_best(wcvp_acc_id_by),
            "wcvp_ipni_id": pick_best(wcvp_ipni_by),
            "wfo_taxon_id": pick_best(wfo_id_by),
            "cites_appendix": pick_best(cites_app_by),
            "cites_full_note": pick_best(cites_note_by),
            "first_published": pick_best(firstpub_by),
            "place_of_publication": pick_best(pop_by),
            "geographic_area": merged_union(x, "geographic_area"),
            "raw_extras": merge_extras(extras_by),
            "sources": "|".join(srcs),
            "synonym_types_observed": "",
            "synonym_type_consensus": "",
            "unique_to_source": srcs[0] if len(srcs) == 1 else "",
            "classification": "unambiguous_accepted",
        })
        rows_a.append(row)

    # 3b. Synonym pair rows — one per unambiguous_synonym binomial.
    for syn, parent in sorted(unambiguous_synonym.items()):
        types_observed: list[str] = []
        srcs_with_pair: list[str] = []
        for s in SOURCES:
            for rec in rows_by_binomial[syn].get(s, []):
                if rec["relation"] == "synonym_of" and rec["synonym_name"] == syn and rec["accepted_name"] == parent:
                    srcs_with_pair.append(s)
                    t = rec.get("synonym_type", "") or "Unknown"
                    types_observed.append(t)
                    break  # one row per source is enough

        distinct_types = []
        for t in types_observed:
            if t and t not in distinct_types:
                distinct_types.append(t)
        non_unknown = [t for t in distinct_types if t != "Unknown"]
        if len(non_unknown) == 1:
            consensus = non_unknown[0]
        elif len(non_unknown) > 1:
            consensus = "Mixed"  # e.g. Homotypic vs Heterotypic disagreement — flagged
        else:
            consensus = "Unknown"

        syn_full_by = field_by_source(syn, "synonym_name_full")
        syn_auth_by = field_by_source(syn, "synonym_authority")
        acc_full_by = field_by_source(parent, "accepted_name_full")
        acc_auth_by = field_by_source(parent, "accepted_authority")
        genus_by = field_by_source(syn, "genus")
        species_by = field_by_source(syn, "species")
        rank_by = field_by_source(syn, "taxon_rank")
        basionym_by = field_by_source(syn, "basionym")
        wcvp_id_by = field_by_source(syn, "wcvp_plant_name_id")
        wcvp_ipni_by = field_by_source(syn, "wcvp_ipni_id")
        wfo_id_by = field_by_source(syn, "wfo_taxon_id")
        extras_by = {s: rows_by_binomial[syn].get(s, [{}])[0].get("raw_extras", "")
                     for s in SOURCES if rows_by_binomial[syn].get(s)}

        row = {col: "" for col in SCHEMA + ["sources", "synonym_types_observed",
                                             "synonym_type_consensus", "unique_to_source",
                                             "classification"]}
        row.update({
            "source": "consolidated",
            "source_record_id": "",
            "relation": "synonym_of",
            "accepted_name": parent,
            "accepted_name_full": pick_best(acc_full_by) or parent,
            "accepted_authority": pick_best(acc_auth_by),
            "synonym_name": syn,
            "synonym_name_full": pick_best(syn_full_by) or syn,
            "synonym_authority": pick_best(syn_auth_by),
            "synonym_type": consensus,
            "family": "Orchidaceae",
            "genus": pick_best(genus_by),
            "species": pick_best(species_by),
            "taxon_rank": pick_best(rank_by),
            "basionym": pick_best(basionym_by),
            "wcvp_plant_name_id": pick_best(wcvp_id_by),
            "wcvp_ipni_id": pick_best(wcvp_ipni_by),
            "wfo_taxon_id": pick_best(wfo_id_by),
            "raw_extras": merge_extras(extras_by),
            "sources": "|".join(srcs_with_pair),
            "synonym_types_observed": "|".join(distinct_types),
            "synonym_type_consensus": consensus,
            "unique_to_source": srcs_with_pair[0] if len(srcs_with_pair) == 1 else "",
            "classification": "unambiguous_synonym",
        })
        rows_a.append(row)

    # 3c. Write Output A
    out_a_cols = SCHEMA + ["sources", "synonym_types_observed",
                            "synonym_type_consensus", "unique_to_source", "classification"]
    df_a = pd.DataFrame(rows_a, columns=out_a_cols)
    path_a = OUT_DIR / "orchid_synonyms_long.csv"
    df_a.to_csv(path_a, index=False)
    print(f"\nOutput A: wrote {len(df_a)} rows to {path_a.relative_to(ROOT)}")
    print(f"  accepted rows: {(df_a['relation']=='accepted').sum()}")
    print(f"  synonym rows:  {(df_a['relation']=='synonym_of').sum()}")
    print(f"  unique-to-one-source: {(df_a['unique_to_source']!='').sum()}")

    # ---------------------------------------------------------------
    # Step 4: build Output B (contested)
    # ---------------------------------------------------------------
    rows_b: list[dict[str, str]] = []
    for x in sorted(contested_status | contested_parent):
        contest_class = "status_conflict" if x in contested_status else "parent_conflict"
        for s in SOURCES:
            recs = rows_by_binomial[x].get(s, [])
            if not recs:
                continue
            # Summarize per-source: what relation does this source assign to x?
            if x in accepted_set[s]:
                rel = "accepted"
                parent = ""
            elif x in synonym_claim[s]:
                rel = "synonym_of"
                parents = sorted(synonym_claim[s][x])
                parent = "|".join(parents)
            else:
                # Edge case: x was the accepted_name of some synonym row in this
                # source (implicit accepted) — counted above.
                rel = "accepted"
                parent = ""

            # Pull the representative record for authority/id fields
            rec = recs[0]
            authority = rec.get("accepted_authority", "") if rel == "accepted" else rec.get("synonym_authority", "")
            rows_b.append({
                "binomial": x,
                "source": s,
                "source_says_relation": rel,
                "source_says_accepted_parent": parent,
                "source_record_id": rec.get("source_record_id", ""),
                "authority": authority,
                "synonym_type": rec.get("synonym_type", ""),
                "contest_class": contest_class,
                "name_full": rec.get("synonym_name_full") if rel == "synonym_of" else rec.get("accepted_name_full", ""),
            })

    df_b = pd.DataFrame(rows_b, columns=[
        "binomial", "source", "source_says_relation", "source_says_accepted_parent",
        "source_record_id", "authority", "synonym_type", "contest_class", "name_full",
    ])
    path_b = OUT_DIR / "contested_names.csv"
    df_b.to_csv(path_b, index=False)
    print(f"\nOutput B: wrote {len(df_b)} rows to {path_b.relative_to(ROOT)}")
    print(f"  status_conflict binomials: {len(contested_status)}")
    print(f"  parent_conflict binomials: {len(contested_parent)}")

    # ---------------------------------------------------------------
    # Step 5: build Output C (unique-to-one-source subset of A)
    # ---------------------------------------------------------------
    df_c = df_a[df_a["unique_to_source"] != ""].copy()
    path_c = OUT_DIR / "unique_to_one_source.csv"
    df_c.to_csv(path_c, index=False)
    print(f"\nOutput C: wrote {len(df_c)} rows to {path_c.relative_to(ROOT)}")
    for s in SOURCES:
        n = (df_c["unique_to_source"] == s).sum()
        print(f"  unique to {s}: {n}")

    # ---------------------------------------------------------------
    # Step 6: report self-synonyms as a separate artifact (infraspecific)
    # ---------------------------------------------------------------
    print(f"\nself-synonyms dropped (likely infraspecific collapsed to binomial):")
    for s in SOURCES:
        print(f"  {s}: {self_synonym_counts[s]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
