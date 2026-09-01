"""Registry describing every data source the pipeline consolidates.

One place that answers "where did this row come from, and what is that source
actually authoritative for?". Both the pipeline and the Streamlit app read this
module, so a new source is added by appending one `Source` entry here plus a
cleaner that writes `data/clean/<id>.csv` in the frozen SCHEMA.

`PIPELINE_ORDER` is the consolidation priority — earlier entries win when two
sources disagree on a scalar field (see scripts/06_consolidate.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Source:
    id: str                      # matches data/clean/<id>.csv and the `source` column
    label: str                   # short human name
    kind: str                    # 'backbone' | 'regulatory' | 'curated' | 'custom'
    one_liner: str               # single sentence for chips/tooltips
    origin: str                  # where the bytes come from
    edition: str                 # which edition/version this build used
    licence: str
    contributes: list[str]       # what this source is authoritative for
    does_not_carry: list[str]    # what it cannot tell you — avoids false expectations
    relations: list[str]         # which `relation` values its rows can take
    colour: str
    homepage: str = ""
    cleaner: str = ""            # the script that produces data/clean/<id>.csv
    notes: str = ""
    provenance_confirmed: bool = True   # False → text is inferred from the cleaner code


WCVP = Source(
    id="wcvp",
    label="Kew WCVP",
    kind="backbone",
    one_liner="Kew's World Checklist of Vascular Plants — the taxonomic backbone.",
    origin=(
        "`wcvp.zip` from Kew's public data repository "
        "(http://sftp.kew.org/pub/data-repositories/WCVP/wcvp.zip), file "
        "`wcvp_names.csv`, pipe-delimited, filtered to `family == 'Orchidaceae'`."
    ),
    edition=(
        "WCVP release of 2026-06-04 (`wcvp.zip`, archived at "
        "`Chigualen/data/raw/wcvp/`). The original build used a pre-filtered "
        "orchid extract dated 2024-06-15, kept for reference at "
        "`Chigualen/data/raw/_originals/orchid_wcvp_2024-06-15.csv`."
    ),
    licence="CC BY 4.0",
    contributes=[
        "Accepted-vs-synonym status for the largest share of names",
        "Homotypic / heterotypic typing (from the `homotypic_synonym` flag)",
        "IPNI identifiers and WCVP `plant_name_id` (used for the POWO link)",
        "Basionym pointer, first-published year, place of publication",
        "Native + introduced distribution, lifeform and climate descriptors",
    ],
    does_not_carry=["CITES appendix or annotations"],
    relations=["accepted", "synonym_of"],
    colour="#2e7d32",
    homepage="https://powo.science.kew.org/",
    cleaner="scripts/01_clean_wcvp.py",
    notes=(
        "Highest consolidation priority: where WCVP and another source disagree "
        "on a scalar field such as authority or rank, WCVP's value is kept."
    ),
)

WFO = Source(
    id="wfo",
    label="World Flora Online",
    kind="backbone",
    one_liner="The WFO Darwin Core backbone — a second, independent global checklist.",
    origin=(
        "WFO DwC backbone (`classification.csv`) out of `_DwC_backbone_R.zip` "
        "on the World Flora Online Plant List Zenodo record, fetched by "
        "`scripts/00_download_wfo.R` or by the Zenodo fallback built into "
        "`scripts/05_clean_wfo.py`, filtered to Orchidaceae."
    ),
    edition=(
        "World Flora Online Plant List 2025-12 — Zenodo, "
        "DOI 10.5281/zenodo.18007552, file `_DwC_backbone_R.zip` (121 MB), "
        "published 2025-12-21, CC0."
    ),
    licence="CC0 1.0",
    contributes=[
        "An independent second opinion on accepted-vs-synonym status",
        "WFO taxon identifiers (`wfo-…`) and the WFO taxon page link",
        "`namePublishedIn` strings and nomenclatural status remarks",
    ],
    does_not_carry=[
        "Homotypic / heterotypic typing — WFO's DwC export does not distinguish "
        "them, so every WFO synonym arrives as type `Unknown`",
        "CITES appendix or annotations",
    ],
    relations=["accepted", "synonym_of"],
    colour="#1565c0",
    homepage="https://www.worldfloraonline.org/",
    cleaner="scripts/05_clean_wfo.py",
    notes=(
        "Because WFO cannot type its synonyms, a pair seen only by WFO shows as "
        "`Unknown` rather than as a disagreement."
    ),
)

CITES_CSV = Source(
    id="cites_csv",
    label="CITES listings CSV",
    kind="regulatory",
    one_liner=(
        "The regulatory listing table: which orchid names are on Appendix I, II "
        "or III, with their annotations and range states."
    ),
    origin=(
        "A Species+ / CITES Checklist comma-separated export, delivered as "
        "`cites_listings_2026-04-22 23_02_comma_separated.csv` and placed at "
        "`Chigualen/data/raw/cites_listings.csv`. The export was already "
        "restricted to Orchidaceae at download time — all 29,347 rows pass the "
        "cleaner's `Family == 'Orchidaceae'` filter."
    ),
    edition="Species+ export taken 2026-04-22, 29,347 orchid listings",
    licence="CITES / UNEP-WCMC terms of use",
    contributes=[
        "The CITES appendix (I / II / III) attached to a name",
        "The full annotation text and its footnote number",
        "`Listed under` — the higher taxon the listing actually hangs off",
        "Range-state distribution: native, introduced, reintroduced, extinct, uncertain",
        "An author citation that usually carries the description year (`Königer, 1994`)",
    ],
    does_not_carry=[
        "Any synonym information at all — every row is read as an accepted listing",
        "Taxonomic identifiers (no IPNI, no WFO id)",
        "A judgement about whether the listed name is taxonomically current",
    ],
    relations=["accepted"],
    colour="#ef6c00",
    homepage="https://speciesplus.net/",
    cleaner="scripts/02_clean_cites_csv.py",
    notes=(
        "This is the source of *legal* status. It says nothing about taxonomy, so "
        "a name that CITES lists is treated here as accepted-by-CITES even when "
        "the botanical backbones have since sunk it into another genus — which is "
        "the single most common cause of a `status_conflict`."
    ),
)

CITES_PDF = Source(
    id="cites_pdf",
    label="CITES Appendix II Orchid Checklist (PDF)",
    kind="regulatory",
    one_liner=(
        "The nomenclatural cross-reference that maps any name on a permit onto "
        "the accepted name used in the listings."
    ),
    origin=(
        "*CITES Appendix II Orchid Checklist* (2022, UNEP-WCMC and the Royal "
        "Botanic Gardens, Kew), Part I — the two-column "
        "'ALL NAMES → ACCEPTED NAME' table. Parsed straight out of the PDF text "
        "layer by font (italic = name, bold italic = accepted binomial)."
    ),
    edition=(
        "2022 edition — `CITES Appendix II Orchid Checklist 2022_EN.pdf`, "
        "521 pages, archived at `Chigualen/data/raw/cites_appendix.pdf`."
    ),
    licence="CITES / UNEP-WCMC / RBG Kew terms of use",
    contributes=[
        "Synonym → accepted-name pairs as used *for CITES purposes*",
        "The authority strings printed alongside both names",
    ],
    does_not_carry=[
        "Homotypic / heterotypic typing — the checklist does not print it, so "
        "every pair arrives as type `Unknown`",
        "The appendix itself (that comes from the listings CSV)",
        "Identifiers of any kind",
    ],
    relations=["synonym_of"],
    colour="#f9a825",
    homepage="https://cites.org/eng/resources/pub/checklist_orchid",
    cleaner="scripts/03_parse_cites_pdf.py",
    notes=(
        "Part II (accepted binomials only) is skipped as redundant with the "
        "listings CSV, and Part III (country checklist) is out of scope. "
        "`source_record_id` is a page/­coordinate stamp (`p214_y381.2_3`) because "
        "the PDF has no record ids — it lets you find the printed line again."
    ),
)

USER_SYNONYMS = Source(
    id="user_synonyms",
    label="Curated synonyms",
    kind="curated",
    one_liner="A hand-curated synonym list contributed by the project team.",
    origin=(
        "`full_synonyms_df.csv`, supplied by the project team and placed at "
        "`Chigualen/data/raw/user_synonyms.csv`. Three columns — "
        "`accepted_name`, `synonym_name`, `status` — where `status` is "
        "`Homotypic_Synonym` or `Heterotypic_Synonym`."
    ),
    edition="team-maintained; 23,369 pairs (8,922 homotypic, 14,447 heterotypic)",
    licence="project-internal",
    contributes=[
        "Synonym pairs with explicit `Homotypic_Synonym` / `Heterotypic_Synonym` typing",
        "Typing for pairs the CITES PDF and WFO can only report as `Unknown`",
    ],
    does_not_carry=["Identifiers, distribution, publication data, CITES appendix"],
    relations=["accepted", "synonym_of"],
    colour="#6a1b9a",
    homepage="",
    cleaner="scripts/04_clean_user_synonyms.py",
    notes="Lowest consolidation priority — it is used to enrich typing, not to override the backbones.",
)


REGISTRY: dict[str, Source] = {
    s.id: s for s in (WCVP, WFO, CITES_CSV, CITES_PDF, USER_SYNONYMS)
}

# Consolidation priority, highest first. scripts/06_consolidate.py imports this.
PIPELINE_ORDER: list[str] = ["wcvp", "wfo", "cites_csv", "cites_pdf", "user_synonyms"]

SOURCE_COLOURS: dict[str, str] = {s.id: s.colour for s in REGISTRY.values()}


def get(source_id: str) -> Source | None:
    return REGISTRY.get(source_id)


def label(source_id: str) -> str:
    s = REGISTRY.get(source_id)
    return s.label if s else source_id


def colour(source_id: str, default: str = "#546e7a") -> str:
    s = REGISTRY.get(source_id)
    return s.colour if s else default


def split_source_list(value: str) -> list[str]:
    """Split a `sources` cell — pipe-joined in the long table, comma-joined in
    the wide table — into an ordered, de-duplicated list of source ids."""
    if not value:
        return []
    out: list[str] = []
    for piece in value.replace("|", ",").split(","):
        piece = piece.strip()
        if piece and piece not in out:
            out.append(piece)
    return out
