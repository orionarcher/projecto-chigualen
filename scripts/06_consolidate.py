"""Consolidate the five cleaned sources into three outputs.

Output A: data/out/orchid_synonyms_consolidated.csv
    Binomials where no cross-source contradiction exists.
    One row per (accepted, synonym) pair, plus accepted-only rows for names
    with no synonyms recorded anywhere.

Output B: data/out/contested_names.csv
    Binomials the sources cannot be reconciled on. One row per (binomial,
    source) — NOT collapsed. `contest_class` says which comparison failed:

      status_conflict   some source calls the name accepted, another calls it a
                        synonym of something else. Compared: the `relation`
                        column across sources.
      parent_conflict   all sources call it a synonym, but they disagree about
                        the parent. Compared: `accepted_name` on synonym rows.
      parent_contested  all sources agree on the parent, but that parent is
                        itself contested. Nothing about this name disagrees.

    Disagreement about `synonym_type` (homotypic vs heterotypic) never makes a
    name contested — those land in Output A with
    synonym_type_consensus == 'Mixed'.

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
from _normalize import SCHEMA, description_year  # noqa: E402
from _sources import PIPELINE_ORDER  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CLEAN_DIR = ROOT / "Chigualen" / "data" / "clean"
OUT_DIR = ROOT / "Chigualen" / "data" / "out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SOURCES = list(PIPELINE_ORDER)
PRIORITY = {s: i for i, s in enumerate(SOURCES)}

# Fields on a cleaned row that describe *the row's own subject* — the accepted
# name on an `accepted` row, the synonym on a `synonym_of` row. They must never
# be harvested from a record that merely names the binomial as somebody else's
# accepted parent, or a species inherits its synonym's genus and identifiers.
# Columns Output A adds on top of the frozen per-source SCHEMA.
OUT_A_EXTRA_COLS = SCHEMA + [
    "description_year",
    "sources",
    "synonym_types_observed",
    "synonym_type_consensus",
    "unique_to_source",
    "classification",
]

SELF_SCOPED_FIELDS = [
    "genus", "species", "infraspecific_rank", "infraspecific_epithet",
    "taxon_rank", "basionym", "wcvp_plant_name_id", "wcvp_ipni_id",
    "wfo_taxon_id", "first_published", "place_of_publication",
    "geographic_area", "cites_appendix", "cites_full_note", "raw_extras",
]


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
    # mention_rows[binomial][source] = every row-dict that names the binomial,
    #     whether as its own subject or as another name's accepted parent.
    # self_rows[binomial][source]    = only the rows whose subject IS the
    #     binomial. Self-scoped metadata (genus, ids, publication) must be read
    #     from here; reading it from mention_rows is how a species used to end
    #     up wearing its synonym's genus and IPNI id.
    accepted_set: dict[str, set[str]] = {s: set() for s in SOURCES}
    synonym_claim: dict[str, dict[str, set[str]]] = {s: defaultdict(set) for s in SOURCES}
    rows_by_binomial: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    self_rows: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
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
                self_rows[acc][source].append(rec)
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
                self_rows[syn][source].append(rec)
                # The parent binomial is indexed as a *mention* only. This row
                # is authoritative for the parent's name and authority (the
                # cleaners resolve those) but not for anything else about it.
                rows_by_binomial[acc][source].append(rec)

    # Cleaners collapse infraspecific taxa onto their binomial, so a source can
    # hold several self records for one binomial: the species itself plus its
    # subspecies and varieties. The species record is the one that describes the
    # binomial, so promote it — otherwise `Vanda falcata` inherits the ids and
    # publication year of whichever subspecies happened to be listed first.
    for by_source in self_rows.values():
        for source, recs in by_source.items():
            recs.sort(key=lambda r: bool(r.get("infraspecific_epithet", "")))

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
    # Kept as its own class: every source agrees where these names belong, the
    # doubt is entirely inherited from the parent. Folding them in with
    # parent_conflict used to make them look like genuine disagreements.
    contested_inherited: set[str] = set(orphaned_by_parent)

    # ---------------------------------------------------------------
    # Step 3: build Output A
    # ---------------------------------------------------------------
    def _first_by_source(index, binomial: str, field: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for s in SOURCES:
            for rec in index[binomial].get(s, []):
                v = rec.get(field, "")
                if v:
                    out.setdefault(s, v)
                    break
        return out

    def self_field(binomial: str, field: str) -> dict[str, str]:
        """Read a field from records whose subject IS this binomial.

        Use for everything in SELF_SCOPED_FIELDS. A record that names the
        binomial only as some synonym's accepted parent describes the synonym,
        not the parent, so it must not be consulted here.
        """
        assert field in SELF_SCOPED_FIELDS, f"{field} is not self-scoped"
        return _first_by_source(self_rows, binomial, field)

    def parent_field(binomial: str, field: str) -> dict[str, str]:
        """Read a field that describes the accepted parent a record points at.

        `accepted_name_full` and `accepted_authority` are resolved by every
        cleaner to describe the parent, so a synonym record is a legitimate
        witness for them even though it is not the parent's own record.
        """
        assert field in {"accepted_name_full", "accepted_authority", "family"}, field
        return _first_by_source(rows_by_binomial, binomial, field)

    def merged_union(binomial: str, field: str, sep: str = "; ") -> str:
        """Union a list-valued self-scoped field across sources, order-preserving."""
        seen: set[str] = set()
        out: list[str] = []
        for s in SOURCES:
            for rec in self_rows[binomial].get(s, []):
                v = rec.get(field, "")
                if not v:
                    continue
                for piece in v.split(sep):
                    piece = piece.strip()
                    if piece and piece not in seen:
                        seen.add(piece)
                        out.append(piece)
        return sep.join(out)

    def year_for(binomial: str, authority_by: dict[str, str],
                 name_full_by: dict[str, str]) -> str:
        """Best available description year.

        `first_published` (WCVP, WFO) is the direct field; the CITES listings CSV
        instead folds the year into its author citation ('Königer, 1994'), so
        fall back to the authority and full-name strings.
        """
        published_by = self_field(binomial, "first_published")
        candidates = [published_by.get(s, "") for s in SOURCES]
        candidates += [authority_by.get(s, "") for s in SOURCES]
        candidates += [name_full_by.get(s, "") for s in SOURCES]
        return description_year(*candidates)

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
        acc_full_by = parent_field(x, "accepted_name_full")
        acc_auth_by = parent_field(x, "accepted_authority")
        family_by = parent_field(x, "family")
        genus_by = self_field(x, "genus")
        species_by = self_field(x, "species")
        rank_by = self_field(x, "taxon_rank")
        basionym_by = self_field(x, "basionym")
        wcvp_id_by = self_field(x, "wcvp_plant_name_id")
        wcvp_ipni_by = self_field(x, "wcvp_ipni_id")
        wfo_id_by = self_field(x, "wfo_taxon_id")
        cites_app_by = self_field(x, "cites_appendix")
        cites_note_by = self_field(x, "cites_full_note")
        firstpub_by = self_field(x, "first_published")
        pop_by = self_field(x, "place_of_publication")
        extras_by = {s: self_rows[x].get(s, [{}])[0].get("raw_extras", "")
                     for s in SOURCES if self_rows[x].get(s)}

        # WCVP's accepted-name id: prefer this binomial's own record, but a
        # synonym record pointing here also names it, so use that as a fallback
        # for species that no source emits an explicit `accepted` row for.
        wcvp_acc_id_by = _first_by_source(self_rows, x, "wcvp_plant_name_id")
        if not any(wcvp_acc_id_by.values()):
            wcvp_acc_id_by = _first_by_source(
                rows_by_binomial, x, "wcvp_accepted_plant_name_id")

        # Genus and species are a property of the binomial itself. Sources may
        # leave them blank (the CITES PDF does for accepted names); derive them
        # rather than shipping a hole.
        name_genus, _, name_species = x.partition(" ")

        srcs = sources_that_mention(x)
        row = {col: "" for col in OUT_A_EXTRA_COLS}
        row.update({
            "source": "consolidated",
            "source_record_id": "",
            "relation": "accepted",
            "accepted_name": x,
            "accepted_name_full": pick_best(acc_full_by) or x,
            "accepted_authority": pick_best(acc_auth_by),
            "family": pick_best(family_by) or "Orchidaceae",
            "genus": pick_best(genus_by) or name_genus,
            "species": pick_best(species_by) or name_species,
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
            "description_year": year_for(x, acc_auth_by, acc_full_by),
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

        syn_full_by = _first_by_source(self_rows, syn, "synonym_name_full")
        syn_auth_by = _first_by_source(self_rows, syn, "synonym_authority")
        acc_full_by = parent_field(parent, "accepted_name_full")
        acc_auth_by = parent_field(parent, "accepted_authority")
        genus_by = self_field(syn, "genus")
        species_by = self_field(syn, "species")
        rank_by = self_field(syn, "taxon_rank")
        basionym_by = self_field(syn, "basionym")
        wcvp_id_by = self_field(syn, "wcvp_plant_name_id")
        wcvp_ipni_by = self_field(syn, "wcvp_ipni_id")
        wfo_id_by = self_field(syn, "wfo_taxon_id")
        extras_by = {s: self_rows[syn].get(s, [{}])[0].get("raw_extras", "")
                     for s in SOURCES if self_rows[syn].get(s)}
        syn_genus, _, syn_species = syn.partition(" ")

        row = {col: "" for col in OUT_A_EXTRA_COLS}
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
            "genus": pick_best(genus_by) or syn_genus,
            "species": pick_best(species_by) or syn_species,
            "taxon_rank": pick_best(rank_by),
            "basionym": pick_best(basionym_by),
            "wcvp_plant_name_id": pick_best(wcvp_id_by),
            "wcvp_ipni_id": pick_best(wcvp_ipni_by),
            "wfo_taxon_id": pick_best(wfo_id_by),
            "raw_extras": merge_extras(extras_by),
            "description_year": year_for(syn, syn_auth_by, syn_full_by),
            "sources": "|".join(srcs_with_pair),
            "synonym_types_observed": "|".join(distinct_types),
            "synonym_type_consensus": consensus,
            "unique_to_source": srcs_with_pair[0] if len(srcs_with_pair) == 1 else "",
            "classification": "unambiguous_synonym",
        })
        rows_a.append(row)

    # 3c. Write Output A
    out_a_cols = OUT_A_EXTRA_COLS
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

    # Exactly what each contest_class means. Written once to
    # contest_class_reference.csv rather than repeated on all 36k contested rows
    # — the app joins it back on for the "how is this decided?" panel.
    CONTEST_CLASS_RULE = {
        "status_conflict": (
            "At least one source records this binomial as an accepted name while "
            "at least one other records it as a synonym of a different name. "
            "Compared field: `relation` (accepted vs synonym_of)."
        ),
        "parent_conflict": (
            "Every source agrees this binomial is a synonym, but they name "
            "different accepted parents for it. Compared field: `accepted_name` "
            "on the synonym rows."
        ),
        "parent_contested": (
            "Every source agrees this binomial is a synonym of one and the same "
            "parent, but that parent is itself contested, so the placement "
            "cannot be resolved. No field disagrees on this name directly."
        ),
    }

    def contest_class_of(binomial: str) -> str:
        if binomial in contested_status:
            return "status_conflict"
        if binomial in contested_inherited:
            return "parent_contested"
        return "parent_conflict"

    for x in sorted(contested_status | contested_parent | contested_inherited):
        contest_class = contest_class_of(x)

        # Roll the disagreement up once per binomial so every row can carry it.
        accepted_in = [s for s in SOURCES if x in accepted_set[s]]
        synonym_in = [s for s in SOURCES if x in synonym_claim[s]]
        claimed_parents: list[str] = []
        for s in synonym_in:
            for parent in sorted(synonym_claim[s][x]):
                if parent not in claimed_parents:
                    claimed_parents.append(parent)
        if contest_class == "parent_contested":
            inherited_from = claimed_parents[0] if claimed_parents else ""
            reason = (
                f"all {len(synonym_in)} source(s) place it in {inherited_from}, "
                f"but {inherited_from} is itself contested"
            )
        elif contest_class == "status_conflict":
            reason = (
                f"accepted by {', '.join(accepted_in)}; "
                f"treated as a synonym by {', '.join(synonym_in)} "
                f"(of {', '.join(claimed_parents)})"
            )
        else:
            reason = f"placed in {len(claimed_parents)} different parents: {', '.join(claimed_parents)}"

        for s in SOURCES:
            recs = rows_by_binomial[x].get(s, [])
            if not recs:
                continue
            # Summarize per-source: what relation does this source assign to x?
            says_synonym = x in synonym_claim[s]
            says_accepted = x in accepted_set[s]
            if says_synonym:
                # A source can say both: it accepts the binomial while filing one
                # of its own infraspecific taxa, which collapses to the same
                # binomial, under a different name. Record both claims — reading
                # `accepted` first is what used to make such rows look unanimous.
                rel = "accepted+synonym_of" if says_accepted else "synonym_of"
                parent = "|".join(sorted(synonym_claim[s][x]))
                evidence = "explicit"
            elif self_rows[x].get(s):
                rel = "accepted"
                parent = ""
                evidence = "explicit"
            else:
                # x is named only as the accepted parent of some other name in
                # this source. That is still this source calling x accepted, but
                # it never emitted a record *about* x.
                rel = "accepted"
                parent = ""
                evidence = "implied_by_synonym_row"

            # The representative record must be one whose subject is x; a
            # parent-mention row would hand back the other name's authority.
            own = self_rows[x].get(s, [])
            rec = own[0] if own else recs[0]
            if own:
                as_accepted = rel == "accepted"
                authority = (rec.get("accepted_authority", "") if as_accepted
                             else rec.get("synonym_authority", ""))
                name_full = (rec.get("accepted_name_full", "") if as_accepted
                             else rec.get("synonym_name_full", ""))
                synonym_type = rec.get("synonym_type", "")
                record_id = rec.get("source_record_id", "")
            else:
                # Implied-accepted: the mention row does resolve x's own name and
                # authority, but nothing else about it.
                authority = rec.get("accepted_authority", "")
                name_full = rec.get("accepted_name_full", "")
                synonym_type = ""
                record_id = ""

            rows_b.append({
                "binomial": x,
                "source": s,
                "source_says_relation": rel,
                "source_says_accepted_parent": parent,
                "source_record_id": record_id,
                "authority": authority,
                "synonym_type": synonym_type,
                "contest_class": contest_class,
                "contest_reason": reason,
                "evidence": evidence,
                "n_sources_accepted": str(len(accepted_in)),
                "n_sources_synonym": str(len(synonym_in)),
                "all_claimed_parents": "|".join(claimed_parents),
                "name_full": name_full,
            })

    df_b = pd.DataFrame(rows_b, columns=[
        "binomial", "source", "source_says_relation", "source_says_accepted_parent",
        "source_record_id", "authority", "synonym_type", "contest_class",
        "contest_reason", "evidence", "n_sources_accepted",
        "n_sources_synonym", "all_claimed_parents", "name_full",
    ])
    path_b = OUT_DIR / "contested_names.csv"
    df_b.to_csv(path_b, index=False)
    print(f"\nOutput B: wrote {len(df_b)} rows to {path_b.relative_to(ROOT)}")
    print(f"  status_conflict binomials:   {len(contested_status)}")
    print(f"  parent_conflict binomials:   {len(contested_parent)}")
    print(f"  parent_contested binomials:  {len(contested_inherited)}")

    ref_path = OUT_DIR / "contest_class_reference.csv"
    pd.DataFrame(
        [{"contest_class": cls, "rule": rule} for cls, rule in CONTEST_CLASS_RULE.items()],
        columns=["contest_class", "rule"],
    ).to_csv(ref_path, index=False)
    print(f"wrote {ref_path.relative_to(ROOT)}")

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
