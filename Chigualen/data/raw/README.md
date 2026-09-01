# Raw sources

Everything the pipeline consumes, gathered in one place.

Two sources download themselves (`scripts/00_download_wcvp.sh`, and the Zenodo
fallback built into `scripts/05_clean_wfo.py`). The other three cannot be
fetched from anywhere — so **`_originals/Chigualen.rar` is committed**. At
5.6 MB it makes the repository self-contained: clone it, unpack the archive,
run the pipeline, and you get the same outputs.

The unpacked data (~330 MB) is not committed — it is reconstructible from the
archive and the two downloads. This README records what every file is, where it
came from, and its SHA-256, so provenance survives in git even where the bytes
do not.

## Inventory

### `cites_listings.csv`

- **Feeds:** `cites_csv` (see `scripts/_sources.py`)
- **Delivered as:** `cites_listings_2026-04-22 23_02_comma_separated.csv`
- **From:** Chigualen.rar
- **Size:** 88.3 MB
- **SHA-256:** `58e9935582729d94dbe8783b7dc8bc6cb297db93de9b97d7bac3ef616689cd34`

Species+ / CITES Checklist comma-separated export, taken 2026-04-22, already restricted to Orchidaceae. 29,347 listings.

### `cites_appendix.pdf`

- **Feeds:** `cites_pdf` (see `scripts/_sources.py`)
- **Delivered as:** `CITES Appendix II Orchid Checklist 2022_EN.pdf`
- **From:** Chigualen.rar
- **Size:** 3.4 MB
- **SHA-256:** `3e3c9854d8f1ad779049dbd6a672248a5c285ac1093b254479b0e373fe3d9275`

CITES Appendix II Orchid Checklist, 2022 edition, UNEP-WCMC & RBG Kew. Part I supplies 12,746 synonym pairs.

### `user_synonyms.csv`

- **Feeds:** `user_synonyms` (see `scripts/_sources.py`)
- **Delivered as:** `full_synonyms_df.csv`
- **From:** Chigualen.rar
- **Size:** 1.6 MB
- **SHA-256:** `e295169f01367eca457310f7995bfceffae5037526f39917475eeac1debd8593`

Team-curated synonym list: accepted_name / synonym_name / status. 23,369 pairs (8,922 homotypic, 14,447 heterotypic).

### `wcvp/wcvp.zip`

- **Feeds:** `wcvp` (see `scripts/_sources.py`)
- **Delivered as:** `wcvp.zip`
- **From:** http://sftp.kew.org/pub/data-repositories/WCVP/wcvp.zip
- **Size:** 88.2 MB
- **SHA-256:** `d32ea2b3a85e489b14e83bcc9eae7274532e1d113753f7be290d4b2dfde573fa`

Kew World Checklist of Vascular Plants, release dated 2026-06-04. `wcvp_names.csv` is the file the cleaner reads.

### `wfo/backbone.zip`

- **Feeds:** `wfo` (see `scripts/_sources.py`)
- **Delivered as:** `_DwC_backbone_R.zip`
- **From:** https://zenodo.org/records/18007552
- **Size:** 121.1 MB
- **SHA-256:** `d0472c3814f3b5bed0af84a4fb7716d36e9200cd585dd1fc9c7b0f244e723ee6`

World Flora Online Plant List 2025-12, DOI 10.5281/zenodo.18007552, published 2025-12-21. `classification.csv` is the file the cleaner reads.

### `_originals/orchid_wcvp_2024-06-15.csv`

- **Feeds:** `—`
- **Delivered as:** `orchid_wcvp.csv`
- **From:** Chigualen.rar
- **Size:** 30.6 MB
- **SHA-256:** `b515efa93d6d91cf37f12d183b606965ab255c48072086de458ca2027a36eb35`

Pre-filtered WCVP orchid extract dated 2024-06-15 — the input the *original* build used. Kept for provenance; the pipeline now reads the full WCVP release above.

### `_originals/Chigualen.rar`

- **Feeds:** `—`
- **Delivered as:** `Chigualen.rar`
- **From:** supplied by the project team
- **Size:** 5.8 MB
- **SHA-256:** `a743d4a3b88770720993c8b5529e747d9cdfa6eb94ec3a1eace245ea1f22618f`

The archive the three non-downloadable sources arrived in, kept intact so the aggregation can be re-done from one file.

## Rebuilding this directory

```bash
# the two self-downloading sources
bash scripts/00_download_wcvp.sh
python3 scripts/05_clean_wfo.py          # downloads the WFO backbone if absent

# the three hand-placed sources, out of the archive
unar -o Chigualen/data/raw/_originals Chigualen/data/raw/_originals/Chigualen.rar
cd Chigualen/data/raw/_originals/Chigualen
cp 'cites_listings_2026-04-22 23_02_comma_separated.csv' ../../cites_listings.csv
cp 'CITES Appendix II Orchid Checklist 2022_EN.pdf'      ../../cites_appendix.pdf
cp full_synonyms_df.csv                                  ../../user_synonyms.csv
```

Then run the pipeline as described in the top-level README.

## Licence and redistribution

| File | Terms |
|---|---|
| `wcvp/wcvp.zip` | CC BY 4.0 — redistributable with attribution |
| `wfo/backbone.zip` | CC0 1.0 — public domain |
| `cites_listings.csv` | CITES / UNEP-WCMC terms of use |
| `cites_appendix.pdf` | UNEP-WCMC and RBG Kew, 2022 — check before redistributing |
| `user_synonyms.csv` | project-internal |

`_originals/Chigualen.rar` is committed on the project's decision, so the
repository stands alone. The two CITES files inside it are the ones to check
before redistributing further — publishing this repository publishes them.
