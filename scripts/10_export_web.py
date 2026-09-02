"""Pack the consolidated outputs into static files a browser can query.

The static build has no server, so every lookup the Streamlit app does against a
DataFrame has to be answerable by fetching a file from a CDN. Two shapes cover
all of it:

  index.json        Loaded once, on first paint. Every binomial the database
                    knows, with just enough to resolve it: what kind of name it
                    is, what it resolves to, which sources say so. This is what
                    search and the batch diff run against, so both stay instant
                    and neither needs a round trip per name.

  species/NN.json   31k species records, hash-sharded. Fetched only when a card
                    is opened. Sharding by hash rather than by initial keeps the
                    shards evenly sized — an alphabetical split puts a tenth of
                    Orchidaceae in `B` alone.
  contested/NN.json Same, for per-source conflict detail.

Strings that repeat across every row (source lists, ranks, synonym types) are
interned into small vocabularies and referenced by integer; the CDN then gzips
what is left. See scripts/_sources.py for the source order the bitmask uses.

    python3 scripts/10_export_web.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from _sources import (  # noqa: E402
    CONTEST_CLASSES,
    PIPELINE_ORDER,
    REGISTRY,
    TYPING_NEVER_CONTESTS,
    split_source_list,
)

ROOT = SCRIPT_DIR.parent
OUT_DIR = ROOT / "Chigualen" / "data" / "out"
WEB_DATA = ROOT / "web" / "data"

SHARDS = 256

KIND_ACCEPTED, KIND_SYNONYM, KIND_CONTESTED = 0, 1, 2
SOURCE_BIT = {s: 1 << i for i, s in enumerate(PIPELINE_ORDER)}


def shard_of(name: str) -> int:
    """Stable string hash — must match the one in web/js/data.js exactly.

    FNV-1a, 32-bit. Chosen over anything language-specific precisely because it
    is trivial to reimplement in JS and cannot drift.
    """
    h = 0x811C9DC5
    for ch in name.lower():
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h % SHARDS


def source_mask(value: str) -> int:
    mask = 0
    for s in split_source_list(value):
        mask |= SOURCE_BIT.get(s, 0)
    return mask


class Vocab:
    """Intern repeated strings; emit them once as a list."""

    def __init__(self) -> None:
        self._ids: dict[str, int] = {}
        self.items: list[str] = []

    def __call__(self, value: str) -> int:
        value = value or ""
        if value not in self._ids:
            self._ids[value] = len(self.items)
            self.items.append(value)
        return self._ids[value]


def write_json(path: Path, payload: object) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    # separators: no whitespace. The CDN gzips, but there is no reason to ship
    # 200k spaces first.
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


def main() -> int:
    wide = pd.read_csv(OUT_DIR / "orchid_synonyms_consolidated.csv", dtype=str, keep_default_na=False)
    long_df = pd.read_csv(OUT_DIR / "orchid_synonyms_long.csv", dtype=str, keep_default_na=False)
    contested = pd.read_csv(OUT_DIR / "contested_names.csv", dtype=str, keep_default_na=False)
    rules = pd.read_csv(OUT_DIR / "contest_class_reference.csv", dtype=str, keep_default_na=False)
    print(f"loaded {len(wide)} species, {len(long_df)} long rows, {len(contested)} contested rows")

    if WEB_DATA.exists():
        shutil.rmtree(WEB_DATA)

    # ---------------------------------------------------------------- index
    accepted = long_df[long_df["relation"] == "accepted"]
    synonyms = long_df[long_df["relation"] == "synonym_of"]

    syn_type_vocab = Vocab()
    contest_class_vocab = Vocab()

    # name → position in `names`; every target is one of these.
    names: list[str] = []
    name_id: dict[str, int] = {}

    def intern_name(value: str) -> int:
        if value not in name_id:
            name_id[value] = len(names)
            names.append(value)
        return name_id[value]

    # key → [kind, targetId, sourceMask, synTypeId]
    entries: dict[str, list[int]] = {}

    for name, srcs in zip(accepted["accepted_name"], accepted["sources"]):
        if not name:
            continue
        entries[name.lower()] = [KIND_ACCEPTED, intern_name(name), source_mask(srcs), 0]

    for name, parent, syn_type, srcs in zip(
        synonyms["synonym_name"], synonyms["accepted_name"],
        synonyms["synonym_type_consensus"], synonyms["sources"],
    ):
        if not name:
            continue
        key = name.lower()
        if entries.get(key, [None])[0] == KIND_ACCEPTED:
            continue  # accepted wins, exactly as in app/data.py
        entries[key] = [KIND_SYNONYM, intern_name(parent), source_mask(srcs),
                        syn_type_vocab(syn_type or "Unknown")]

    contested_class_by_name = dict(zip(contested["binomial"], contested["contest_class"]))
    for name in contested["binomial"].unique():
        if not name:
            continue
        entries[name.lower()] = [
            KIND_CONTESTED, intern_name(name), 0,
            contest_class_vocab(contested_class_by_name.get(name, "")),
        ]

    # Per-species scalars the resolver needs without opening a shard.
    year_by = dict(zip(wide["accepted_name"], wide["description_year"]))
    appendix_by = dict(zip(wide["accepted_name"], wide["cites_appendix"]))
    appendix_vocab = Vocab()
    species_scalars = {}
    for name in names:
        if name in year_by:
            species_scalars[name_id[name]] = [year_by[name], appendix_vocab(appendix_by.get(name, ""))]

    keys = sorted(entries)
    index = {
        "sources": PIPELINE_ORDER,
        "sourceLabels": {s: REGISTRY[s].label for s in PIPELINE_ORDER},
        "sourceShort": {s: REGISTRY[s].short for s in PIPELINE_ORDER},
        "sourceColours": {s: REGISTRY[s].colour for s in PIPELINE_ORDER},
        "shards": SHARDS,
        "names": names,
        "keys": keys,
        "entries": [entries[k] for k in keys],
        "synTypes": syn_type_vocab.items,
        "contestClasses": contest_class_vocab.items,
        "appendices": appendix_vocab.items,
        "speciesScalars": species_scalars,
        "contestRules": dict(zip(rules["contest_class"], rules["rule"])),
        "counts": {
            "species": len(wide),
            "synonymPairs": int((long_df["relation"] == "synonym_of").sum()),
            "contested": int(contested["binomial"].nunique()),
        },
    }
    index_bytes = write_json(WEB_DATA / "index.json", index)
    print(f"index.json: {index_bytes/1e6:.1f} MB, {len(keys)} keys, {len(names)} names")

    # Everything the Data sources page renders. Its own file rather than part of
    # index.json: only that page needs it, and index.json is on the critical path
    # for first paint.
    sources_payload = {
        "sources": [
            {
                "id": src.id, "label": src.label, "short": src.short, "kind": src.kind,
                "oneLiner": src.one_liner, "origin": src.origin,
                "edition": src.edition, "licence": src.licence,
                "contributes": src.contributes, "doesNotCarry": src.does_not_carry,
                "relations": src.relations, "homepage": src.homepage,
                "cleaner": src.cleaner, "notes": src.notes,
                "provenanceConfirmed": src.provenance_confirmed,
                "speciesTouched": int(wide["sources"].str.contains(src.id, regex=False).sum()),
            }
            for src in (REGISTRY[s] for s in PIPELINE_ORDER)
        ],
        "contestClasses": [
            {"id": c.id, "title": c.title, "colour": c.colour, "summary": c.summary,
             "detail": c.detail, "example": c.example}
            for c in CONTEST_CLASSES
        ],
        "typingNeverContests": TYPING_NEVER_CONTESTS,
        "contestClassCounts": {
            cls: int(n) for cls, n in
            contested.drop_duplicates("binomial")["contest_class"].value_counts().items()
        },
        "counts": {
            "species": len(wide),
            "synonymPairs": int((long_df["relation"] == "synonym_of").sum()),
            "contested": int(contested["binomial"].nunique()),
            "withYear": int((wide["description_year"] != "").sum()),
        },
    }
    sources_bytes = write_json(WEB_DATA / "sources.json", sources_payload)
    print(f"sources.json: {sources_bytes/1e3:.0f} kB")

    # Source colours as a real stylesheet rather than inline style attributes.
    # The site ships a Content-Security-Policy with no 'unsafe-inline', which is
    # the point of this build -- an uploaded checklist cannot be exfiltrated by
    # injected markup -- so colours have to arrive as CSS from our own origin.
    css = [
        "/* Generated by scripts/10_export_web.py from scripts/_sources.py.",
        "   Add a Source() entry there and its colour appears here. */",
    ]
    for source_id in PIPELINE_ORDER:
        colour = REGISTRY[source_id].colour
        css.append(
            f".src-{source_id} {{ color: {colour}; background: {colour}22; "
            f"border-color: {colour}55; }}"
        )
    css_path = WEB_DATA.parent / "css" / "sources.css"
    css_path.parent.mkdir(parents=True, exist_ok=True)
    css_path.write_text("\n".join(css) + "\n", encoding="utf-8")
    print(f"sources.css: {len(PIPELINE_ORDER)} source colours")

    # ------------------------------------------------------------- species
    CARD_FIELDS = [
        "accepted_name_full", "accepted_authority", "family", "genus", "species",
        "taxon_rank", "description_year", "cites_appendix", "cites_full_note",
        "wcvp_plant_name_id", "wcvp_ipni_id", "wfo_taxon_id", "basionym",
        "first_published", "place_of_publication", "geographic_area",
        "synonyms_detailed", "contested_synonyms", "sources", "classification",
    ]
    species_shards: dict[int, dict] = defaultdict(dict)
    for rec in wide.to_dict("records"):
        name = rec["accepted_name"]
        species_shards[shard_of(name)][name] = {
            k: rec.get(k, "") for k in CARD_FIELDS if rec.get(k, "")
        }

    total = 0
    for shard, payload in species_shards.items():
        total += write_json(WEB_DATA / "species" / f"{shard:03d}.json", payload)
    print(f"species/: {len(species_shards)} shards, {total/1e6:.1f} MB total, "
          f"{total/max(len(species_shards),1)/1e3:.0f} kB average")

    # ----------------------------------------------------------- contested
    CONTEST_FIELDS = ["source", "source_says_relation", "source_says_accepted_parent",
                      "authority", "synonym_type", "evidence", "source_record_id", "name_full"]
    contested_shards: dict[int, dict] = defaultdict(dict)
    for binomial, group in contested.groupby("binomial", sort=False):
        rows = group.to_dict("records")
        contested_shards[shard_of(binomial)][binomial] = {
            "contestClass": rows[0].get("contest_class", ""),
            "reason": rows[0].get("contest_reason", ""),
            "rows": [{k: r.get(k, "") for k in CONTEST_FIELDS if r.get(k, "")} for r in rows],
        }

    total_c = 0
    for shard, payload in contested_shards.items():
        total_c += write_json(WEB_DATA / "contested" / f"{shard:03d}.json", payload)
    print(f"contested/: {len(contested_shards)} shards, {total_c/1e6:.1f} MB total, "
          f"{total_c/max(len(contested_shards),1)/1e3:.0f} kB average")

    # Every deploy rewrites these files at the same URLs, so `immutable` caching
    # would mean a returning visitor never sees a rebuilt database. Stamp a build
    # id derived from the content; web/js/data.js appends it as ?v= so the URL
    # changes whenever the data does, and stays stable when it does not.
    build_id = hashlib.sha256((WEB_DATA / "index.json").read_bytes()).hexdigest()[:12]
    build_path = WEB_DATA.parent / "build.json"
    build_path.write_text(json.dumps({"build": build_id}), encoding="utf-8")
    print(f"build id: {build_id}")

    grand = index_bytes + sources_bytes + total + total_c
    print(f"\ntotal uncompressed: {grand/1e6:.1f} MB")
    print(f"first paint fetches index.json only: {index_bytes/1e6:.1f} MB "
          f"(~{index_bytes/1e6/3.5:.1f} MB gzipped)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
