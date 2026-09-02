"""Repair the committed out/ artifacts in place.

Why this exists
---------------
Until the provenance fix in `06_consolidate.py`, a binomial's own metadata was
harvested from *any* cleaned record that named it — including records that named
it only as some other name's accepted parent. Those records describe the
synonym, so ~40% of species in the shipped
`data/out/orchid_synonyms_consolidated.csv` carried their synonym's genus,
species epithet, IPNI id, WFO id, basionym and publication data. `Stelis
ariasii` was filed under genus *Anathallis*; `Vanda falcata` under
*Holcoglossum*, and both linked to the wrong POWO page.

`06_consolidate.py` no longer does this. But rebuilding from scratch needs the
raw inputs of all five sources, and three of them (the CITES listings CSV, the
CITES Appendix II PDF and the curated synonym list) are not committed. This
script repairs the committed artifact in place instead, re-deriving every
self-scoped field from the two backbones that supply them — WCVP and WFO —
which *are* reproducible with `scripts/00_download_wcvp.sh` and
`scripts/05_clean_wfo.py`.

Fields owned by the CITES listings CSV (`cites_appendix`, `cites_full_note`)
were never affected: every one of its rows is `accepted`, so it can only ever
describe its own subject.

After a full five-source rebuild this script is a no-op — it reports
`0 rows changed`, which doubles as a regression check on 06.

It does two things:

1. Re-derives every self-scoped field on `orchid_synonyms_long.csv`, and fills
   in the new `description_year`.
2. Backfills the columns that explain `contest_class` onto
   `contested_names.csv`, so the shipped file answers "why is this contested?"
   without anyone reverse-engineering the rule. The one column that cannot be
   recovered post-hoc is `evidence` — knowing whether a source emitted a record
   *about* a name or only named it as somebody else's parent needs the cleaned
   inputs — so it is written as `unknown` here and filled properly by a real
   rebuild.

Run from project root, then re-run 08 to refresh the wide outputs:
    python3 scripts/09_repair_outputs.py
    python3 scripts/08_wide_format.py
"""

from __future__ import annotations

import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from _normalize import description_year  # noqa: E402
from _sources import CONTEST_CLASS_RULE  # noqa: E402

ROOT = SCRIPT_DIR.parent
CLEAN_DIR = ROOT / "Chigualen" / "data" / "clean"
OUT_DIR = ROOT / "Chigualen" / "data" / "out"
LONG_PATH = OUT_DIR / "orchid_synonyms_long.csv"
CONTESTED_PATH = OUT_DIR / "contested_names.csv"

# Only the backbones can contaminate: they are the sources that emit
# `synonym_of` rows carrying rich self-scoped metadata. Priority order.
BACKBONES = ["wcvp", "wfo"]

# Self-scoped scalar fields, and which backbone can supply each.
# `infraspecific_rank` / `infraspecific_epithet` are deliberately absent: the
# long table is binomial-scoped, and WFO reports 'species' in its
# verbatimTaxonRank field, which would fill 60k rows with a non-answer.
REPAIR_FIELDS = [
    "genus",
    "species",
    "taxon_rank",
    "basionym",
    "wcvp_plant_name_id",
    "wcvp_ipni_id",
    "wfo_taxon_id",
    "first_published",
    "place_of_publication",
]

# raw_extras keys each backbone owns. Repair drops these, then re-adds them from
# the correct record; keys belonging to the three uncommitted sources are kept.
BACKBONE_EXTRA_KEYS = {
    "wcvp": {"lifeform_description", "climate_description", "hybrid",
             "nomenclatural_remarks", "volume_and_page", "wcvp_taxon_status_raw"},
    "wfo": {"wfo_taxonomic_status_raw", "wfo_nomenclatural_status",
            "originalNameUsageID", "taxonRemarks", "references", "source",
            "majorGroup", "tplId", "higherClassification"},
}
ALL_BACKBONE_EXTRA_KEYS = set().union(*BACKBONE_EXTRA_KEYS.values())

GEO_SEP = "; "



def load_backbone(name: str) -> pd.DataFrame | None:
    path = CLEAN_DIR / f"{name}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    print(f"loaded clean/{name}.csv: {len(df)} rows")
    return df


def build_indexes(frames: dict[str, pd.DataFrame]):
    """self[source][binomial] and mention[source][binomial], preserving file order.

    `self` holds records whose subject is the binomial; `mention` additionally
    holds records that name it as a synonym's accepted parent — i.e. exactly the
    rows the old consolidation wrongly read metadata from.
    """
    self_idx: dict[str, dict[str, list[dict]]] = {s: defaultdict(list) for s in frames}
    mention_idx: dict[str, dict[str, list[dict]]] = {s: defaultdict(list) for s in frames}
    for source, df in frames.items():
        for rec in df.to_dict("records"):
            acc, syn = rec["accepted_name"], rec["synonym_name"]
            if rec["relation"] == "accepted":
                self_idx[source][acc].append(rec)
                mention_idx[source][acc].append(rec)
            elif rec["relation"] == "synonym_of":
                if syn and syn != acc:
                    self_idx[source][syn].append(rec)
                    mention_idx[source][syn].append(rec)
                    mention_idx[source][acc].append(rec)
    # Match 06: the species record outranks its own subspecies and varieties,
    # which the cleaners collapse onto the same binomial.
    for by_binomial in self_idx.values():
        for recs in by_binomial.values():
            recs.sort(key=lambda r: bool(r.get("infraspecific_epithet", "")))
    return self_idx, mention_idx


def first_nonempty(recs: list[dict], field: str) -> str:
    for rec in recs:
        v = rec.get(field, "")
        if v:
            return v
    return ""


def union_pieces(recs: list[dict], field: str) -> list[str]:
    out: list[str] = []
    for rec in recs:
        for piece in (rec.get(field, "") or "").split(GEO_SEP):
            piece = piece.strip()
            if piece and piece not in out:
                out.append(piece)
    return out


def repair_contested() -> None:
    """Add the explanatory columns to contested_names.csv.

    Everything here is derived from the per-source rows already in the file, so
    it stays true to what the consolidation actually decided.
    """
    if not CONTESTED_PATH.exists():
        print(f"\n{CONTESTED_PATH.name} not found — skipping contested backfill")
        return

    df = pd.read_csv(CONTESTED_PATH, dtype=str, keep_default_na=False)
    print(f"\nloaded contested table: {len(df)} rows")
    contested_binomials = set(df["binomial"])
    original_class = dict(zip(df["binomial"], df["contest_class"]))

    per_binomial: dict[str, dict] = {}
    for binomial, group in df.groupby("binomial", sort=False):
        # `accepted+synonym_of` means one source says both — it counts on each
        # side, exactly as 06 counts it when it writes the file.
        relation = group["source_says_relation"]
        syn_rows = group[relation.str.contains("synonym_of", regex=False)]
        accepted_in = sorted(set(group[relation.str.startswith("accepted")]["source"]))
        synonym_in = sorted(set(syn_rows["source"]))
        parents: list[str] = []
        for value in syn_rows["source_says_accepted_parent"]:
            for parent in str(value).split("|"):
                parent = parent.strip()
                if parent and parent not in parents:
                    parents.append(parent)

        if accepted_in and synonym_in:
            contest_class = "status_conflict"
            reason = (
                f"accepted by {', '.join(accepted_in)}; "
                f"treated as a synonym by {', '.join(synonym_in)} "
                f"(of {', '.join(parents)})"
            )
        elif len(parents) > 1:
            contest_class = "parent_conflict"
            reason = f"placed in {len(parents)} different parents: {', '.join(parents)}"
        elif parents:
            # One agreed parent and no source calls it accepted: the doubt is
            # inherited from the parent, which must itself be contested.
            inherited = parents[0]
            contest_class = "parent_contested"
            reason = (
                f"all {len(synonym_in)} source(s) place it in {inherited}, "
                f"but {inherited} is itself contested"
            )
        else:
            # Every row says 'accepted' and none names a parent, yet the
            # consolidation flagged the name. The consolidation that produced
            # this file resolved `accepted` before `synonym_of`, so a source
            # that said both was recorded only as accepting — the synonym claim
            # is simply not in the file. Keep the original verdict and say so
            # rather than inventing a parent conflict that the rows do not show.
            contest_class = original_class.get(binomial, "status_conflict")
            reason = (
                "flagged by the consolidation, but the per-source detail in this "
                "build does not show which source treated it as a synonym — "
                "rebuild with scripts/06_consolidate.py to recover it"
            )

        per_binomial[binomial] = {
            "contest_class": contest_class,
            "contest_reason": reason,
            "n_sources_accepted": str(len(accepted_in)),
            "n_sources_synonym": str(len(synonym_in)),
            "all_claimed_parents": "|".join(parents),
        }

    reclassified = sum(1 for b, meta in per_binomial.items()
                       if meta["contest_class"] != original_class.get(b))

    for column in ("contest_class", "contest_reason",
                   "n_sources_accepted", "n_sources_synonym", "all_claimed_parents"):
        df[column] = [per_binomial[b][column] for b in df["binomial"]]
    if "evidence" not in df.columns:
        df["evidence"] = "unknown"

    ordered = [
        "binomial", "source", "source_says_relation", "source_says_accepted_parent",
        "source_record_id", "authority", "synonym_type", "contest_class",
        "contest_reason", "evidence", "n_sources_accepted",
        "n_sources_synonym", "all_claimed_parents", "name_full",
    ]
    df = df[[c for c in ordered if c in df.columns]]

    backup = CONTESTED_PATH.with_suffix(".csv.pre-repair")
    if not backup.exists():
        shutil.copy2(CONTESTED_PATH, backup)
        print(f"backed up original to {backup.relative_to(ROOT)}")
    df.to_csv(CONTESTED_PATH, index=False)
    print(f"wrote {len(df)} rows to {CONTESTED_PATH.relative_to(ROOT)}")
    counts = df.drop_duplicates("binomial")["contest_class"].value_counts().to_dict()
    for cls, n in sorted(counts.items()):
        print(f"  {cls:<18} {n:>6} binomials")
    print(f"  ({reclassified} binomials moved to a more precise class)")

    ref_path = OUT_DIR / "contest_class_reference.csv"
    pd.DataFrame(
        [{"contest_class": cls, "rule": rule} for cls, rule in CONTEST_CLASS_RULE.items()],
        columns=["contest_class", "rule"],
    ).to_csv(ref_path, index=False)
    print(f"wrote {ref_path.relative_to(ROOT)}")


def main() -> int:
    if not LONG_PATH.exists():
        print(f"ERROR: {LONG_PATH} not found", file=sys.stderr)
        return 1

    frames = {}
    for name in BACKBONES:
        df = load_backbone(name)
        if df is None:
            print(
                f"ERROR: {CLEAN_DIR / (name + '.csv')} is missing.\n"
                f"       Rebuild it first:\n"
                f"         bash scripts/00_download_wcvp.sh && python3 scripts/01_clean_wcvp.py\n"
                f"         python3 scripts/05_clean_wfo.py",
                file=sys.stderr,
            )
            return 1
        frames[name] = df

    self_idx, mention_idx = build_indexes(frames)

    long_df = pd.read_csv(LONG_PATH, dtype=str, keep_default_na=False)
    print(f"loaded long table: {len(long_df)} rows")

    if "description_year" not in long_df.columns:
        long_df["description_year"] = ""
        # Keep the new column next to the other derived ones rather than last.
        cols = list(long_df.columns)
        cols.remove("description_year")
        cols.insert(cols.index("sources"), "description_year")
        long_df = long_df[cols]

    records = long_df.to_dict("records")
    changed_rows = 0
    field_changes: dict[str, int] = defaultdict(int)

    for rec in records:
        # The row's own subject: the accepted name on an accepted row, the
        # synonym on a synonym row.
        subject = rec["accepted_name"] if rec["relation"] == "accepted" else rec["synonym_name"]
        if not subject:
            continue

        row_changed = False

        # Only WCVP and WFO can contaminate — they are the sources that emit
        # synonym rows carrying rich self-scoped metadata, and only the rows
        # where this binomial is *not* the subject could have leaked into it.
        leaky_rows: list[dict] = []
        for src in BACKBONES:
            own = self_idx[src].get(subject, [])
            own_ids = {id(r) for r in own}
            leaky_rows += [r for r in mention_idx[src].get(subject, [])
                           if id(r) not in own_ids]

        # ---- scalar self-scoped fields ----
        for field in REPAIR_FIELDS:
            new = ""
            for source in BACKBONES:
                new = first_nonempty(self_idx[source].get(subject, []), field)
                if new:
                    break
            if not new and field == "wcvp_plant_name_id":
                # WCVP files some species only as the parent of a synonym; those
                # rows still name the accepted taxon's id.
                new = first_nonempty(
                    mention_idx["wcvp"].get(subject, []), "wcvp_accepted_plant_name_id")
            if not new and field in ("genus", "species"):
                # Never leave a hole: the binomial itself is authoritative.
                genus, _, species = subject.partition(" ")
                new = genus if field == "genus" else species
            if not new:
                # Nothing to put here. Only clear the field if its current value
                # demonstrably came off a backbone row describing some *other*
                # name; otherwise a lower-priority source supplied it honestly
                # (the CITES listings carry `taxon_rank` for species neither
                # backbone holds) and blanking it would be a regression.
                existing = rec.get(field, "")
                if not existing or existing not in {r.get(field, "") for r in leaky_rows}:
                    continue
            if new != rec.get(field, ""):
                field_changes[field] += 1
                rec[field] = new
                row_changed = True

        # wcvp_accepted_plant_name_id on an accepted row is that row's own id.
        if rec["relation"] == "accepted":
            acc_id = rec["wcvp_plant_name_id"]
            if acc_id != rec.get("wcvp_accepted_plant_name_id", ""):
                field_changes["wcvp_accepted_plant_name_id"] += 1
                rec["wcvp_accepted_plant_name_id"] = acc_id
                row_changed = True

        # ---- geographic_area ----
        # Drop only the pieces the backbones contributed through a parent-mention
        # row; pieces from the CITES listings CSV are untouched because that
        # source has no synonym rows to leak from.
        wrong_pieces: set[str] = set()
        right_pieces: list[str] = []
        for source in BACKBONES:
            mention = set(union_pieces(mention_idx[source].get(subject, []), "geographic_area"))
            own = union_pieces(self_idx[source].get(subject, []), "geographic_area")
            wrong_pieces |= mention - set(own)
            for piece in own:
                if piece not in right_pieces:
                    right_pieces.append(piece)
        existing = [p for p in (rec.get("geographic_area", "") or "").split(GEO_SEP) if p.strip()]
        kept = [p.strip() for p in existing if p.strip() not in wrong_pieces]
        merged = right_pieces + [p for p in kept if p not in right_pieces]
        new_geo = GEO_SEP.join(merged)
        if new_geo != rec.get("geographic_area", ""):
            field_changes["geographic_area"] += 1
            rec["geographic_area"] = new_geo
            row_changed = True

        # ---- raw_extras ----
        try:
            blob = json.loads(rec.get("raw_extras", "") or "{}")
        except ValueError:
            blob = {}
        rebuilt = {k: v for k, v in blob.items() if k not in ALL_BACKBONE_EXTRA_KEYS}
        for source in BACKBONES:
            # First self record only, matching 06's `self_rows[x][s][0]`.
            own = self_idx[source].get(subject, [])
            if not own:
                continue
            try:
                own_blob = json.loads(own[0].get("raw_extras", "") or "{}")
            except ValueError:
                continue
            for k, v in own_blob.items():
                if k in BACKBONE_EXTRA_KEYS[source] and k not in rebuilt:
                    rebuilt[k] = v
        new_extras = (json.dumps(rebuilt, ensure_ascii=False, sort_keys=True, default=str)
                      if rebuilt else "")
        if new_extras != rec.get("raw_extras", ""):
            field_changes["raw_extras"] += 1
            rec["raw_extras"] = new_extras
            row_changed = True

        # ---- description_year ----
        if rec["relation"] == "accepted":
            authority, name_full = rec["accepted_authority"], rec["accepted_name_full"]
        else:
            authority, name_full = rec["synonym_authority"], rec["synonym_name_full"]
        # 06 can see every source's authority string and so finds years this
        # cannot — the CITES listings write 'Archila, 2010' where WFO's
        # namePublishedIn has no year at all. Never overwrite a year with a blank.
        year = description_year(rec["first_published"], authority, name_full)
        if not year:
            year = rec.get("description_year", "")
        if year != rec.get("description_year", ""):
            field_changes["description_year"] += 1
            rec["description_year"] = year
            row_changed = True

        if row_changed:
            changed_rows += 1

    print(f"\nrows changed: {changed_rows} / {len(records)}")
    for field, n in sorted(field_changes.items(), key=lambda kv: -kv[1]):
        print(f"  {field:<30} {n:>7}")

    if changed_rows == 0:
        print("\nnothing to repair — the long table is already consistent.")
        repair_contested()
        return 0

    backup = LONG_PATH.with_suffix(".csv.pre-repair")
    if not backup.exists():
        shutil.copy2(LONG_PATH, backup)
        print(f"\nbacked up original to {backup.relative_to(ROOT)}")

    out = pd.DataFrame(records, columns=list(long_df.columns))
    out.to_csv(LONG_PATH, index=False)
    print(f"wrote {len(out)} rows to {LONG_PATH.relative_to(ROOT)}")

    repair_contested()
    print("\nnow re-run: python3 scripts/08_wide_format.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
