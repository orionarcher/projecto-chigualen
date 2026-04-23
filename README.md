# Projecto Chigualen

Consolidated orchid species database across five authoritative sources, with a
local Streamlit app for search and authority-CSV diffing.

## What's inside

**Pipeline** — five per-source cleaners write to a uniform schema, one
consolidation step produces wide + long tables plus a contested-names pile, a
summary report, and a unique-to-one-source subset.

| Source | Role | Rows contributed (orchids) |
|---|---|---|
| Kew WCVP | taxonomic backbone | 33,378 accepted + 57,385 synonyms |
| World Flora Online | global checklist | 33,128 accepted + 63,737 synonyms |
| CITES listings CSV | regulatory | 29,347 accepted |
| CITES Appendix II PDF | regulatory + synonym pairs | 12,746 synonym pairs |
| User-curated synonyms | Homotypic/Heterotypic typing | 23,369 synonym pairs |

The consolidated wide table lives at
[`Chigualen/data/out/orchid_synonyms_consolidated.csv`](Chigualen/data/out/orchid_synonyms_consolidated.csv):
31,498 species, one row each, with comma-separated synonyms and sources.

**App** — a Streamlit app (`app/`) that reads the consolidated outputs and
offers:

1. **Search** by accepted name or synonym, with a species card showing sources,
   synonyms (typed), CITES appendix, taxonomy, publication, distribution, and
   external links to POWO / WFO.
2. **Ingest** an authority CSV. Map the name column; the app diffs every row
   against the database and reports matches (accepted / synonym), missing,
   contested, and unparseable — with per-category CSV downloads.

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

## Outputs

- `Chigualen/data/out/orchid_synonyms_consolidated.csv` — **primary**, wide
- `Chigualen/data/out/orchid_synonyms_long.csv` — one row per synonym pair
- `Chigualen/data/out/contested_names.csv` — per-source disagreement detail
- `Chigualen/data/out/unique_to_one_source.csv` — species backed by a single source
- `Chigualen/data/out/conflicts_summary.csv` — summary stats

## Attribution

- WCVP (Kew) — CC BY 4.0
- World Flora Online — CC0 1.0
- CITES Appendix II Orchid Checklist 2022 — UNEP-WCMC, Kew
