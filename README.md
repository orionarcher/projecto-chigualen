# Projecto Chigualen

Consolidated orchid species database across five authoritative sources, with a
local Streamlit app for search and authority-CSV diffing.

## What's inside

**Pipeline** — five per-source cleaners write to a uniform schema, one
consolidation step produces wide + long tables plus a contested-names pile, a
summary report, and a unique-to-one-source subset.

| Source | Role | What it is authoritative for | Rows contributed (orchids) |
|---|---|---|---|
| **Kew WCVP** (`wcvp`) | taxonomic backbone | status, homotypic/heterotypic typing, IPNI + WCVP ids, basionym, publication, distribution | 33,734 accepted + 57,672 synonyms |
| **World Flora Online** (`wfo`) | taxonomic backbone | an independent second opinion on status, WFO taxon ids | 33,128 accepted + 63,737 synonyms |
| **CITES listings CSV** (`cites_csv`) | regulatory — *legal status* | which appendix a name is on, the annotation, range states, author citation with year | 29,347 accepted |
| **CITES Appendix II PDF** (`cites_pdf`) | regulatory — *nomenclature* | synonym → accepted mapping as used for CITES | 12,746 synonym pairs |
| **Curated synonyms** (`user_synonyms`) | curated | homotypic/heterotypic typing the other sources cannot supply | 23,369 synonym pairs |

`cites_csv` and `cites_pdf` are **not two formats of one dataset**. The listings
CSV answers *is this name regulated, and how?*; the Appendix II checklist PDF
answers *what is the current name for the name on this permit?*. Neither
substitutes for the other, and a name being accepted in the listings while every
botanical backbone treats it as a synonym is a real regulatory fact, not a data
error. Full descriptions — origin, licence, what each source cannot tell you —
live in [`scripts/_sources.py`](scripts/_sources.py) and are rendered on the
app's **Data sources** page.

The consolidated wide table lives at
[`Chigualen/data/out/orchid_synonyms_consolidated.csv`](Chigualen/data/out/orchid_synonyms_consolidated.csv):
31,498 species, one row each, with comma-separated synonyms and sources.

**App** — a Streamlit app (`app/`) that reads the consolidated outputs and
offers:

1. **Search** by accepted name or synonym, with a species card showing sources,
   synonyms (typed), disputed names filed under the species, CITES appendix,
   taxonomy, publication (including the description year), distribution,
   external links to POWO / WFO, and a **per-source panel** giving each source's
   own verdict.
2. **Ingest** an authority CSV. Map the name column; every row is diffed against
   the database and the export carries a `_status` / `_accepted_name` pair **per
   source**, the `contest_class` and plain-language `contest_reason` behind any
   contested verdict, and the description year — so a contested batch no longer
   has to be re-checked one name at a time.
3. **Your own checklists** — load an authority's internal backbone (WISIA, a
   national checklist, a nursery register) and it is compared alongside the five
   built-in sources everywhere in the app, with its own export columns.
   Session-only; nothing is written to disk.
4. **Data sources** — what each source is, where it comes from, and the exact
   rules behind `contest_class`.

## How conflicts are classified

A name the sources cannot be reconciled on is held out of the consolidated table
and written to `contested_names.csv` instead, one row per source.
`contest_class` records **which comparison failed**:

| class | meaning | fields compared |
|---|---|---|
| `status_conflict` | some source calls the name accepted, another calls it a synonym of something else | `relation` (`accepted` vs `synonym_of`) |
| `parent_conflict` | all sources call it a synonym, but name different parents | `accepted_name` on the synonym rows |
| `parent_contested` | all sources agree on the parent, but the parent is itself contested | nothing on this name — inherited |

**A disagreement about `synonym_type` never makes a name contested.** Homotypic
vs heterotypic disagreements stay in the consolidated table with
`synonym_type_consensus = Mixed`. Authority strings and infraspecific taxa are
not compared either — everything is compared at binomial rank.

Each contested row also carries `contest_reason` (the specific disagreement in
words), `n_sources_accepted` / `n_sources_synonym`, `all_claimed_parents`, and
`evidence` (`explicit`, or `implied_by_synonym_row` when a source never
published a record about the name and only cited it as another name's parent).
The rules themselves live once in `contest_class_reference.csv`.

Contested names are also linked back from the species they were proposed under,
via the `contested_synonyms` column of the wide table — so searching *Stelis
ariasii* now shows that *Anathallis ariasii*, which CITES still lists as
accepted, is the same plant.

## Running locally

```bash
pip install -r requirements.txt
streamlit run app/app.py
```

Open http://localhost:8501.

## Regenerating the pipeline

The raw source data is not committed (1.4 GB of PDFs, zips, and CSVs). To
rebuild from scratch:

```bash
# download raw data
bash scripts/00_download_wcvp.sh           # Kew WCVP (~85 MB zip)
Rscript scripts/00_download_wfo.R          # World Flora Online
# (manually place the CITES PDF + CITES listings CSV + user synonyms CSV in Chigualen/)

# clean + consolidate
python3 scripts/01_clean_wcvp.py
python3 scripts/02_clean_cites_csv.py
python3 scripts/03_parse_cites_pdf.py
python3 scripts/04_clean_user_synonyms.py
python3 scripts/05_clean_wfo.py
python3 scripts/06_consolidate.py
python3 scripts/07_report_conflicts.py
python3 scripts/08_wide_format.py
```

Only WCVP and WFO download themselves; the three other raw inputs must be placed
by hand. `scripts/09_repair_outputs.py` exists because of that asymmetry — see
below.

## Adding a data source

The pipeline is registry-driven, so a new source (the **CITES Standard
Nomenclatures**, current or historical, are the obvious next ones) needs three
things and nothing else:

1. a cleaner emitting `Chigualen/data/clean/<id>.csv` in the frozen `SCHEMA` in
   [`scripts/_normalize.py`](scripts/_normalize.py);
2. one `Source(...)` entry appended to
   [`scripts/_sources.py`](scripts/_sources.py) — this drives the app's Data
   sources page, the colour coding, and the export columns;
3. its id added to `PIPELINE_ORDER` at the priority it deserves.

Consolidation, the conflict classes, the species cards and the batch export all
read the registry. A historical edition enters as its own source rather than
replacing the current one, so an edition-to-edition disagreement surfaces as an
ordinary `status_conflict`.

## Tests

```bash
python3 tests/test_consolidation.py
```

Builds a miniature five-source fixture reproducing the record shapes behind the
reported bugs, runs the real `06` and `08` over it, and asserts the results —
including that a species never inherits its synonym's genus or identifiers, that
contested names stay visible from the species they were proposed under, and that
each `contest_class` comes out right. This is the only way to exercise the full
pipeline from a checkout, since three of the five raw inputs are not committed.

## Outputs

- `Chigualen/data/out/orchid_synonyms_consolidated.csv` — **primary**, wide
- `Chigualen/data/out/orchid_synonyms_long.csv` — one row per synonym pair
- `Chigualen/data/out/contested_names.csv` — per-source disagreement detail
- `Chigualen/data/out/contest_class_reference.csv` — the rule behind each class
- `Chigualen/data/out/unique_to_one_source.csv` — species backed by a single source
- `Chigualen/data/out/conflicts_summary.csv` — summary stats

## `scripts/09_repair_outputs.py`

Until the provenance fix in `06_consolidate.py`, a binomial's own metadata was
harvested from *any* cleaned record that named it — including records that named
it only as some other name's accepted parent. Those records describe the
synonym, so about 40% of species carried their synonym's genus, species epithet,
IPNI id, WFO id, basionym and publication data: *Stelis ariasii* was filed under
genus *Anathallis*, *Vanda falcata* under *Holcoglossum*, and both linked to the
wrong POWO page.

`06_consolidate.py` no longer does this, but a full rebuild needs the raw inputs
of all five sources and three of them are not committed. `09_repair_outputs.py`
repairs the committed artifacts instead, re-deriving every self-scoped field from
the two backbones that supply them (WCVP and WFO — both reproducible), and
backfilling the columns that explain `contest_class`:

```bash
bash scripts/00_download_wcvp.sh && python3 scripts/01_clean_wcvp.py
python3 scripts/05_clean_wfo.py
python3 scripts/09_repair_outputs.py
python3 scripts/07_report_conflicts.py
python3 scripts/08_wide_format.py
```

After a full five-source rebuild it reports `0 rows changed`, which doubles as a
regression check on 06.

**Known remaining issue.** 489 accepted binomials in the shipped data are
malformed — 250 carry PDF ligature codepoints (`divitiﬂora` rather than
`divitiflora`) and 267 are infraspecific names that leaked in as binomials. All
489 come from `03_parse_cites_pdf.py`. `norm_text` now folds ligatures, so a
rerun of that parser plus 06 and 08 clears them; they cannot be repaired from the
committed outputs alone because the synonym rows pointing at them would have to
be re-consolidated.

## Attribution

- WCVP (Kew) — CC BY 4.0
- World Flora Online — CC0 1.0
- CITES Appendix II Orchid Checklist 2022 — UNEP-WCMC, Kew
- CITES species listings — CITES / UNEP-WCMC terms of use
