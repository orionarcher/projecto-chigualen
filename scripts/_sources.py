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
    id: str                      # internal only: data/clean/<id>.csv, the `source`
                                 # column, and export column prefixes. Never shown
                                 # as a name in the interface.
    label: str                   # what people read
    short: str                   # chip-sized version of the same name
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
    label="World Checklist of Vascular Plants",
    short="Kew WCVP",
    kind="backbone",
    one_liner=(
        "Kew's global checklist, and the taxonomic backbone of this database — "
        "the default answer to what a species is currently called."
    ),
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
        "Where two sources give different values for the same detail — an "
        "authority string, a rank — Kew's is the one kept."
    ),
)

WFO = Source(
    id="wfo",
    label="World Flora Online",
    short="WFO",
    kind="backbone",
    one_liner=(
        "A second global checklist, compiled independently of Kew's — the reason "
        "this database can tell agreement from consensus of one."
    ),
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
        "Because it cannot distinguish homotypic from heterotypic synonyms, a pair "
        "only this source records is shown as typed *Unknown* — which means "
        "nobody classified it, not that anybody disagreed."
    ),
)

CITES_CSV = Source(
    id="cites_csv",
    label="CITES Listings",
    short="CITES Listings",
    kind="regulatory",
    one_liner=(
        "Which orchid names are regulated, and how. This is the source of legal "
        "status — the appendix a name sits on, its annotation, and its range "
        "states. It says nothing about whether the name is taxonomically current."
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
        "A name that CITES lists is treated here as accepted *by CITES*, even when "
        "the botanical checklists have since moved it into another genus. That is "
        "the single most common reason a name ends up contested, and it is a real "
        "regulatory fact rather than an error — which is why such names are "
        "surfaced rather than quietly resolved one way or the other."
    ),
)

CITES_PDF = Source(
    id="cites_pdf",
    label="CITES Appendix II Orchid Checklist",
    short="CITES Checklist",
    kind="regulatory",
    one_liner=(
        "The official cross-reference from any name that might appear on a permit "
        "to the name CITES uses for it. Where the Listings tell you a name's legal "
        "status, this tells you which name to look that status up under."
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
        "listings, and Part III (the country checklist) is out of scope. The PDF "
        "carries no record numbers, so each pair is stamped with the page and "
        "position it was read from — enough to find the printed line again."
    ),
)

USER_SYNONYMS = Source(
    id="user_synonyms",
    label="Curated Synonyms",
    short="Curated",
    kind="curated",
    one_liner=(
        "A hand-checked synonym list from the project team, carrying the "
        "homotypic/heterotypic distinction that the two CITES sources and WFO "
        "cannot supply."
    ),
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
    notes=(
        "Used to fill in detail the other sources leave blank, never to overrule "
        "them on whether a name is accepted."
    ),
)


@dataclass(frozen=True)
class ContestClass:
    """One way the sources can fail to agree on a name.

    Canonical here because four places need it and they had drifted into three
    copies: the consolidation that assigns it, the repair script that backfills
    it, the Streamlit page that explains it, and the static build's export.
    """
    id: str            # internal: the value written to contested_names.csv
    title: str         # what people read
    colour: str
    summary: str       # the whole rule, in one sentence
    detail: str        # what the consolidation actually compared
    example: str

    @property
    def rule(self) -> str:
        """The single string written to contest_class_reference.csv."""
        return f"{self.summary} {self.detail}"


CONTEST_CLASSES: list[ContestClass] = [
    ContestClass(
        id="status_conflict",
        title="Status conflict",
        colour="#c62828",
        summary="One source calls the name accepted; another calls it a synonym of something else.",
        detail="Decided by comparing whether each source files the name as accepted or as a synonym.",
        example=(
            "The CITES Listings accept *Anathallis ariasii*; Kew and WFO both treat "
            "it as a synonym of *Stelis ariasii*."
        ),
    ),
    ContestClass(
        id="parent_conflict",
        title="Parent conflict",
        colour="#ef6c00",
        summary="Every source agrees the name is a synonym — but not of the same species.",
        detail="Decided by comparing the accepted species each source files the synonym under.",
        example=(
            "*Heteranthocidium ariasii* is filed under *Oncidium ariasii* by one "
            "source and under a different species by another."
        ),
    ),
    ContestClass(
        id="parent_contested",
        title="Inherited doubt",
        colour="#f9a825",
        summary="Nothing about this name is disputed; the species it belongs to is.",
        detail="Nothing on this name was compared — the doubt is carried over from its accepted species.",
        example=(
            "*Oncidium isidrense* is unanimously a synonym of *Oncidium ariasii*, "
            "and *Oncidium ariasii* is itself a status conflict."
        ),
    ),
]

CONTEST_CLASS_BY_ID: dict[str, ContestClass] = {c.id: c for c in CONTEST_CLASSES}
CONTEST_CLASS_RULE: dict[str, str] = {c.id: c.rule for c in CONTEST_CLASSES}

# The question the CITES authority asked outright, and the answer, kept next to
# the rules it qualifies rather than in a section of its own.
TYPING_NEVER_CONTESTS = (
    "A disagreement about whether a synonym is homotypic or heterotypic never "
    "makes a name contested. Those pairs stay in the database, typed **Mixed** in "
    "the synonym table on the species card."
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
