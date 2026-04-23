"""Clean World Flora Online orchid dataset into the uniform Chigualen schema.

Expects Chigualen/data/raw/wfo_orchids.csv produced by scripts/00_download_wfo.R.

If that file is missing, this script will try to recover — first by reading an
already-unzipped classification.txt/classification.csv under
Chigualen/data/raw/wfo/, otherwise by downloading the Zenodo mirror of the WFO
DwC backbone and extracting it. This makes the pipeline resilient to systems
without R installed.

Writes Chigualen/data/clean/wfo.csv.

Run from project root:
    python3 scripts/05_clean_wfo.py
"""

from __future__ import annotations

import sys
import zipfile
from collections import Counter
from pathlib import Path
from urllib.request import urlopen

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from _normalize import (  # noqa: E402
    SCHEMA,
    blank_row,
    norm_text,
    binomial,
    strip_hybrid,
    pack_extras,
    validate_frame,
)

PROJECT_ROOT = SCRIPT_DIR.parent
RAW_DIR = PROJECT_ROOT / "Chigualen" / "data" / "raw"
WFO_DIR = RAW_DIR / "wfo"
INPUT_PATH = RAW_DIR / "wfo_orchids.csv"
OUTPUT_PATH = PROJECT_ROOT / "Chigualen" / "data" / "clean" / "wfo.csv"

ZENODO_URL = (
    "https://zenodo.org/records/18007552/files/_DwC_backbone_R.zip?download=1"
)

# Map WFO taxonomicStatus -> (relation, synonym_type).
# WFO does not distinguish homotypic/heterotypic at this level, so synonyms
# are all tagged "Unknown" unless nomenclaturalStatus tells us otherwise.
STATUS_MAP: dict[str, tuple[str, str]] = {
    "Accepted": ("accepted", ""),
    "Synonym": ("synonym_of", "Unknown"),
    "Ambiguous": ("synonym_of", "Unknown"),
    "Doubtful": ("synonym_of", "Unknown"),
    "Misapplied": ("synonym_of", "Unknown"),
    "Unchecked": ("synonym_of", "Unknown"),
}

# Non-Accepted statuses whose literal value must be preserved in raw_extras.
_PRESERVE_STATUS_RAW = {"Ambiguous", "Doubtful", "Misapplied", "Unchecked"}


def _find_classification_file() -> Path | None:
    """Find a classification.txt or classification.csv under WFO_DIR."""
    if not WFO_DIR.exists():
        return None
    for pattern in ("**/classification.txt", "**/classification.csv"):
        matches = sorted(WFO_DIR.glob(pattern))
        if matches:
            return matches[0]
    return None


def _download_zenodo() -> Path:
    """Download the Zenodo mirror zip and unzip it into WFO_DIR.

    Returns the path to the extracted classification file.
    """
    WFO_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = WFO_DIR / "backbone.zip"
    print(f"downloading {ZENODO_URL}")
    print(f"  -> {zip_path}")
    with urlopen(ZENODO_URL) as resp, open(zip_path, "wb") as fh:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
    print(f"unzipping {zip_path}")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(WFO_DIR)
    found = _find_classification_file()
    if found is None:
        raise RuntimeError(
            f"Zenodo download extracted but no classification file found under {WFO_DIR}"
        )
    return found


def _strip_wrapping_quotes(val: str) -> str:
    """Strip a single pair of wrapping double-quotes left by QUOTE_NONE parsing."""
    if isinstance(val, str) and len(val) >= 2 and val.startswith('"') and val.endswith('"'):
        return val[1:-1]
    return val


def _build_orchids_csv_from_classification(classification_path: Path) -> None:
    """Read classification file, filter to Orchidaceae, write wfo_orchids.csv.

    Used as a fallback when the R download script hasn't been run. We stream
    the full classification file in chunks because it's ~900MB.
    """
    print(f"reading {classification_path} (streaming) to build {INPUT_PATH.name}")
    total = 0
    orchid_rows: list[pd.DataFrame] = []
    # The file is tab-separated. Its quoting is inconsistent (unbalanced
    # quotes inside HTML blobs), so we use QUOTE_NONE. Encoding is mostly
    # UTF-8 but has stray bytes, so we replace on decode errors.
    reader = pd.read_csv(
        classification_path,
        sep="\t",
        dtype=str,
        keep_default_na=False,
        chunksize=200_000,
        quoting=3,  # csv.QUOTE_NONE
        encoding="utf-8",
        encoding_errors="replace",
        on_bad_lines="skip",
    )
    for chunk in reader:
        total += len(chunk)
        sub = chunk[chunk["family"] == "Orchidaceae"]
        if len(sub):
            orchid_rows.append(sub)
    if not orchid_rows:
        raise RuntimeError("No Orchidaceae rows found in classification file")
    orchids = pd.concat(orchid_rows, ignore_index=True)
    # QUOTE_NONE leaves literal wrapping double-quotes on many fields;
    # strip one pair so downstream values are clean.
    for col in orchids.columns:
        orchids[col] = orchids[col].map(_strip_wrapping_quotes)
    print(f"classification total rows: {total}")
    print(f"Orchidaceae rows: {len(orchids)}")
    INPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    orchids.to_csv(INPUT_PATH, index=False)
    print(f"wrote {len(orchids)} rows to {INPUT_PATH.relative_to(PROJECT_ROOT)}")


def ensure_input_available() -> None:
    """Make sure wfo_orchids.csv exists; if not, build it from classification.

    Tries, in order:
      1. Existing wfo_orchids.csv (produced by R script).
      2. Existing classification.txt/.csv under wfo/ (R partially ran, or user
         unzipped manually).
      3. Fresh download from Zenodo.
    """
    if INPUT_PATH.exists():
        print(f"using existing {INPUT_PATH.relative_to(PROJECT_ROOT)}")
        return
    print(f"{INPUT_PATH.name} not found; attempting to recover without R")
    classification = _find_classification_file()
    if classification is None:
        print("no local classification file; downloading from Zenodo mirror")
        classification = _download_zenodo()
    _build_orchids_csv_from_classification(classification)


def build_full_name(scientific_name: str, authorship: str) -> str:
    name = norm_text(scientific_name)
    auth = norm_text(authorship)
    if name and auth and auth not in name:
        return f"{name} {auth}"
    return name


def detect_orth_variant(nomenclatural_status: str) -> bool:
    """Return True if the nomenclaturalStatus marker indicates an orth. var."""
    s = nomenclatural_status.lower()
    return ("orth. var" in s) or ("orthographic" in s)


def main() -> None:
    ensure_input_available()

    print(f"\nreading {INPUT_PATH.relative_to(PROJECT_ROOT)}")
    df = pd.read_csv(INPUT_PATH, dtype=str, keep_default_na=False)
    print(f"total input rows: {len(df)}")

    # Defensive family filter (R script should have already filtered).
    before = len(df)
    df = df[df["family"] == "Orchidaceae"].copy()
    print(f"after Orchidaceae filter: {len(df)} (dropped {before - len(df)})")

    # Enumerate taxonomicStatus vocabulary.
    status_counts = df["taxonomicStatus"].replace("", "<missing>").value_counts()
    print("\ntaxonomicStatus distinct values (with counts):")
    for status, n in status_counts.items():
        print(f"  {status!r}: {n}")

    unexpected_seen: Counter[str] = Counter()
    for status, n in status_counts.items():
        if status == "<missing>":
            unexpected_seen[status] = n
            print(f"  WARNING: missing taxonomicStatus for {n} rows; treating as synonym_of/Unknown")
        elif status not in STATUS_MAP:
            unexpected_seen[status] = n
            print(
                f"  WARNING: unexpected taxonomicStatus {status!r} ({n} rows); "
                f"mapping to synonym_of/Unknown and preserving raw"
            )

    # taxonID -> lookup fields for accepted-parent resolution.
    id_lookup: dict[str, dict[str, str]] = {}
    for _, r in df.iterrows():
        tid = norm_text(r.get("taxonID"))
        if not tid:
            continue
        id_lookup[tid] = {
            "genus": norm_text(r.get("genus")),
            "specificEpithet": norm_text(r.get("specificEpithet")),
            "scientificName": norm_text(r.get("scientificName")),
            "scientificNameAuthorship": norm_text(r.get("scientificNameAuthorship")),
        }

    out_rows: list[dict[str, str]] = []
    dropped_bad_binomial = 0
    failed_parent_lookup = 0
    accepted_count = 0
    synonym_count = 0

    for _, r in df.iterrows():
        tid = norm_text(r.get("taxonID"))
        raw_status = norm_text(r.get("taxonomicStatus"))
        nom_status = norm_text(r.get("nomenclaturalStatus"))

        if raw_status in STATUS_MAP:
            relation, syn_type = STATUS_MAP[raw_status]
            status_was_unexpected = False
        else:
            relation, syn_type = ("synonym_of", "Unknown")
            status_was_unexpected = True

        # nomenclaturalStatus may upgrade a synonym to an orthographic variant.
        if relation == "synonym_of" and detect_orth_variant(nom_status):
            syn_type = "Orthographic variant"

        genus_val = norm_text(r.get("genus"))
        species_val = norm_text(r.get("specificEpithet"))

        this_binom = strip_hybrid(binomial(genus_val, species_val))
        if not this_binom:
            dropped_bad_binomial += 1
            continue

        this_sci_name = norm_text(r.get("scientificName"))
        this_auth = norm_text(r.get("scientificNameAuthorship"))
        this_full = build_full_name(this_sci_name, this_auth)

        accepted_id = norm_text(r.get("acceptedNameUsageID"))

        # Resolve accepted parent.
        if relation == "accepted":
            parent_binom = this_binom
            parent_full = this_full
            parent_authority = this_auth
        else:
            parent = id_lookup.get(accepted_id) if accepted_id else None
            parent_binom = ""
            if parent is not None:
                pb = strip_hybrid(binomial(parent["genus"], parent["specificEpithet"]))
                if pb:
                    parent_binom = pb
                    parent_authority = parent["scientificNameAuthorship"]
                    parent_full = build_full_name(
                        parent["scientificName"], parent["scientificNameAuthorship"]
                    )
            if not parent_binom:
                failed_parent_lookup += 1
                if failed_parent_lookup <= 5:
                    print(
                        f"  WARNING: taxonID={tid} status={raw_status!r} "
                        f"acceptedNameUsageID={accepted_id!r} could not be resolved; "
                        f"falling back to self binomial"
                    )
                parent_binom = this_binom
                parent_full = this_full
                parent_authority = this_auth

        # Extras blob.
        extras: dict[str, object] = {}
        if status_was_unexpected or raw_status in _PRESERVE_STATUS_RAW:
            extras["wfo_taxonomic_status_raw"] = raw_status or "<missing>"
        if nom_status:
            extras["wfo_nomenclatural_status"] = nom_status
        for key in ("originalNameUsageID", "taxonRemarks", "references", "source",
                    "majorGroup", "tplId", "tplID", "higherClassification"):
            val = norm_text(r.get(key))
            if val:
                # Normalize tplID -> tplId for consistency.
                out_key = "tplId" if key in ("tplId", "tplID") else key
                extras[out_key] = val

        row = blank_row()
        row["source"] = "wfo"
        row["source_record_id"] = tid
        row["relation"] = relation
        row["accepted_name"] = parent_binom
        row["accepted_name_full"] = parent_full
        row["accepted_authority"] = parent_authority

        if relation == "synonym_of":
            row["synonym_name"] = this_binom
            row["synonym_name_full"] = this_full
            row["synonym_authority"] = this_auth
            row["synonym_type"] = syn_type
            synonym_count += 1
        else:
            accepted_count += 1

        row["family"] = "Orchidaceae"
        row["genus"] = genus_val
        row["species"] = species_val
        row["infraspecific_epithet"] = norm_text(r.get("infraspecificEpithet"))
        row["infraspecific_rank"] = norm_text(r.get("verbatimTaxonRank"))
        row["taxon_rank"] = norm_text(r.get("verbatimTaxonRank"))
        row["wfo_taxon_id"] = tid
        # wcvp_*, cites_*, basionym, place_of_publication, geographic_area blank.
        row["first_published"] = norm_text(r.get("namePublishedIn"))
        row["raw_extras"] = pack_extras(extras)

        out_rows.append(row)

    out_df = pd.DataFrame(out_rows, columns=SCHEMA)

    print()
    print(f"accepted rows: {accepted_count}")
    print(f"synonym rows: {synonym_count}")
    print(f"dropped (no binomial): {dropped_bad_binomial}")
    print(f"synonym rows with unresolved accepted parent: {failed_parent_lookup}")

    validate_frame(out_df)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(OUTPUT_PATH, index=False)
    rel_out = OUTPUT_PATH.relative_to(PROJECT_ROOT)
    print(f"wrote {len(out_df)} rows to {rel_out}")


if __name__ == "__main__":
    main()
