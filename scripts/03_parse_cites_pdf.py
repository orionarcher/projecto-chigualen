"""Parse CITES Appendix II Orchid Checklist 2022 PDF — Part I (All Names).

Extracts synonym -> accepted-name pairs from the two-column "ALL NAMES ->
ACCEPTED NAME" table that spans most of Part I. Writes the result into the
frozen uniform schema at Chigualen/data/clean/cites_pdf.csv.

Part II (accepted binomials only) and Part III (country checklist) are
intentionally skipped — Part II is redundant with the CITES CSV, Part III is
out of scope.

Font cheat-sheet for this LaTeX-generated PDF:
  CMTI10    -> italic                 (synonym names)
  CMR10     -> regular                 (authorities and connector words)
  CMBXTI10  -> bold italic             (accepted binomials / genus headings)
  CMBX10    -> bold upright            (authorities on accepted names,
                                        column headers "ALL NAMES" etc.)
  CMCSC10   -> small caps running header "Part I: All names in current usage"
  CMBX12    -> large bold section title (only on Part opener pages)

Run from the project root:
    python3 scripts/03_parse_cites_pdf.py
"""

from __future__ import annotations

import random
import re
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
import pymupdf

# Make scripts/ importable when run from the project root.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _normalize import (  # noqa: E402
    SCHEMA,
    blank_row,
    binomial,
    norm_text,
    pack_extras,
    strip_hybrid,
    validate_frame,
)

PROJECT_ROOT = SCRIPT_DIR.parent
INPUT_PATH = PROJECT_ROOT / "Chigualen" / "data" / "raw" / "cites_appendix.pdf"
OUTPUT_PATH = PROJECT_ROOT / "Chigualen" / "data" / "clean" / "cites_pdf.csv"

# Heuristic thresholds tuned on this PDF (page width 595.3pt).
# Both columns start at x~62.8 (left) and x~363.9 (right). Midline ~300.
COLUMN_SPLIT_X = 300.0
# Two spans share a "row" when their y0 differs by < this many points.
ROW_Y_TOLERANCE = 2.0
# Page top margin: header "ALL NAMES / ACCEPTED NAME" band sits around y<=85.
BODY_Y_MIN = 90.0

# Running header font names — strip these before processing.
HEADER_FONTS = {"CMCSC10"}
# Noise text (dot-leader between name and page number in Part I table).
# Dot-leader is typographic guides between name and page number, rendered as
# ". . . . . . ." (dot-space-dot-space...). Require at least 3 spaced dots so
# we don't accidentally eat an abbreviation period followed by 1-2 leaders.
DOT_LEADER_RE = re.compile(r"(?:\s\.){2,}\s*")
# Trailing page-number suffix that survives after dot-leader removal.
TRAILING_PAGENUM_RE = re.compile(r"\s+\d{1,4}\s*$")

# Connector words that appear between binomial and infraspecific epithet,
# rendered in CMR10 (regular). They separate the primary from the subtaxon.
INFRA_CONNECTORS = {"var.", "subsp.", "f.", "subvar.", "subf.", "nothosubsp.", "nothovar."}


def is_italic_span(span: dict) -> bool:
    """CMTI10 -> italic, but not bold-italic."""
    return span["font"] == "CMTI10"


def is_bold_italic_span(span: dict) -> bool:
    """CMBXTI10 -> bold italic."""
    return span["font"] == "CMBXTI10"


def is_bold_upright_span(span: dict) -> bool:
    """CMBX10 -> bold upright (authority or column header)."""
    return span["font"] == "CMBX10"


def is_regular_span(span: dict) -> bool:
    """CMR10 -> regular (authorities on synonyms, connector words)."""
    return span["font"] == "CMR10"


def clean_text_fragment(s: str) -> str:
    """Strip dot-leader and trailing page-number noise from a span group."""
    s = DOT_LEADER_RE.sub(" ", s)
    s = TRAILING_PAGENUM_RE.sub("", s)
    s = norm_text(s)
    # Collapse accidental double-trailing-period that happens when the PDF
    # renders 'Clem..' because the author abbreviation period sits right
    # before the first dot-leader character.
    s = re.sub(r"\.\.+$", ".", s)
    return s


def find_part_ranges(doc: pymupdf.Document) -> tuple[int, int]:
    """Locate Part I content page range by scanning for the large section headers.

    Returns (part_i_first_page, part_i_last_page_inclusive) using 0-indexed
    pdf page numbers. The first content page is the page AFTER the Part I
    opener (which is a single-page title). The last Part I page is the page
    BEFORE the Part II opener.
    """
    part_openers: dict[int, int] = {}  # roman-numeral-index -> pdf page
    for pnum in range(len(doc)):
        page = doc[pnum]
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if span["size"] < 15:
                        continue
                    txt = span["text"].strip()
                    for idx, label in ((1, "Part I:"), (2, "Part II:"), (3, "Part III:")):
                        if txt.startswith(label) and idx not in part_openers:
                            part_openers[idx] = pnum
    if 1 not in part_openers or 2 not in part_openers:
        raise RuntimeError(f"couldn't locate Part I / Part II openers: {part_openers}")
    part_i_first = part_openers[1] + 1  # skip opener title page
    part_i_last = part_openers[2] - 1   # last content page before Part II
    return part_i_first, part_i_last


def collect_spans(page: pymupdf.Page) -> list[dict]:
    """Extract all spans from a page as a flat list of dicts with bbox/font/text."""
    out = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type", 0) != 0:
            continue  # skip images
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if span["font"] in HEADER_FONTS:
                    continue
                if span["bbox"][1] < BODY_Y_MIN:
                    continue  # column header band
                txt = span["text"]
                if not txt.strip():
                    continue
                out.append(span)
    return out


def group_into_rows(spans: list[dict]) -> list[list[dict]]:
    """Cluster spans into rows by their y0 coordinate.

    A row is a list of spans with near-identical y0, sorted by x. Rows are
    returned sorted top-to-bottom.
    """
    if not spans:
        return []
    spans_sorted = sorted(spans, key=lambda s: (s["bbox"][1], s["bbox"][0]))
    rows: list[list[dict]] = []
    current: list[dict] = [spans_sorted[0]]
    current_y = spans_sorted[0]["bbox"][1]
    for s in spans_sorted[1:]:
        if abs(s["bbox"][1] - current_y) <= ROW_Y_TOLERANCE:
            current.append(s)
        else:
            current.sort(key=lambda x: x["bbox"][0])
            rows.append(current)
            current = [s]
            current_y = s["bbox"][1]
    current.sort(key=lambda x: x["bbox"][0])
    rows.append(current)
    return rows


def split_row_by_column(row: list[dict]) -> tuple[list[dict], list[dict]]:
    """Partition a row's spans into left-column and right-column."""
    left = [s for s in row if s["bbox"][0] < COLUMN_SPLIT_X]
    right = [s for s in row if s["bbox"][0] >= COLUMN_SPLIT_X]
    return left, right


def row_y(row: list[dict]) -> float:
    return row[0]["bbox"][1]


# ----------------------------------------------------------------------------
# Logical entry reconstruction within a single column.
#
# An "entry" is one taxonomic name + authority, possibly wrapping over 2 lines
# (continuation lines start at x ~76.9, indented ~14pt from the normal ~62.8).
# Each entry is classified by the first (leftmost-on-first-line) span:
#   italic (CMTI10)       -> synonym entry (left column only, normally)
#   bold-italic (CMBXTI10) -> accepted-name entry (genus heading, cross-ref in
#                             left column, or right-column target)
# Other leading fonts (regular alone, bold-upright alone) are continuation
# lines that attach to the previous entry.
# ----------------------------------------------------------------------------

# The x-indent for column continuation lines. The main body starts at ~62.8
# (left col) or ~363.9 (right col). Wrapped continuation lines start at
# ~76.9 (left) or ~378.0 (right) — roughly +14pt indent.
LEFT_COL_START_X = 62.8
RIGHT_COL_START_X = 363.9
COL_INDENT_TOLERANCE = 3.0  # pt, around the start X


def row_starts_new_entry(column_spans: list[dict], column_start_x: float) -> bool:
    """True if this column's spans look like a NEW entry rather than a wrap."""
    if not column_spans:
        return False
    first = column_spans[0]
    x0 = first["bbox"][0]
    # If the first span sits at the column's flush-left start X, it's a new
    # entry. If it's indented further, it's a wrap of the previous entry.
    return abs(x0 - column_start_x) <= COL_INDENT_TOLERANCE


def classify_entry_head(column_spans: list[dict]) -> str:
    """Return 'italic', 'bolditalic', or 'other' based on the leading span."""
    if not column_spans:
        return "other"
    head = column_spans[0]
    if is_italic_span(head):
        return "italic"
    if is_bold_italic_span(head):
        return "bolditalic"
    return "other"


class Entry:
    """One logical taxonomic entry occupying one or more consecutive lines."""

    __slots__ = ("kind", "y_start", "y_end", "spans", "page")

    def __init__(self, kind: str, y: float, page: int):
        self.kind = kind  # 'italic' or 'bolditalic'
        self.y_start = y
        self.y_end = y
        self.spans: list[dict] = []
        self.page = page

    def extend(self, spans: list[dict], y: float) -> None:
        # Mark a line-wrap so combined_text() can inject a space between the
        # last span of the previous row and the first span of this row. Spans
        # produced by pymupdf for wrapped lines often drop the trailing/
        # leading whitespace that a human reader relies on.
        if self.spans and abs(y - self.y_end) > ROW_Y_TOLERANCE:
            self.spans.append({"text": " ", "font": "__WRAP__", "bbox": (0, y, 0, y)})
        self.spans.extend(spans)
        self.y_end = y

    def combined_text(self) -> str:
        """Concatenate spans preserving original order (already sorted by x per row)."""
        return "".join(s["text"] for s in self.spans)


def build_entries_for_column(
    rows: list[list[dict]],
    column: str,
    page_num: int,
) -> list[Entry]:
    """Walk rows top-to-bottom, attach continuation lines to their head entry."""
    if column == "left":
        col_start = LEFT_COL_START_X
    elif column == "right":
        col_start = RIGHT_COL_START_X
    else:
        raise ValueError(column)

    entries: list[Entry] = []
    current: Entry | None = None
    for row in rows:
        left, right = split_row_by_column(row)
        col_spans = left if column == "left" else right
        if not col_spans:
            continue
        y = col_spans[0]["bbox"][1]
        starts_new = row_starts_new_entry(col_spans, col_start)
        head = classify_entry_head(col_spans)
        if starts_new:
            # Close current (if any) and open new entry — but only if the
            # head is italic or bold-italic. Regular-only starts shouldn't
            # really happen at flush-left; if they do, skip them.
            if head in {"italic", "bolditalic"}:
                current = Entry(head, y, page_num)
                current.extend(col_spans, y)
                entries.append(current)
            else:
                current = None  # unknown start — don't attach wraps to it
        else:
            # Continuation / wrap line — attach to current entry.
            if current is not None:
                current.extend(col_spans, y)
            # else: orphan wrap (shouldn't happen often) — drop silently.
    return entries


# ----------------------------------------------------------------------------
# Text parsing: split "Genus species <authority>" into (name, authority).
# ----------------------------------------------------------------------------

# Author fragments commonly start with an uppercase letter, parens, or specific
# botanical shorthand. Our rule: the binomial ends after the SPECIES epithet
# (the second word, all lowercase, possibly hybrid-marked). Anything further
# is authority. For infraspecific taxa we allow "Genus species <rank> epithet"
# where <rank> is in INFRA_CONNECTORS, then authority follows.
#
# We build the split on the cleaned text. An approximation that works well for
# this PDF: scan whitespace-separated tokens. Take up to 2 tokens (genus +
# species) as the binomial. If token-3 is a connector (var./subsp./f.) AND
# token-4 is an all-lowercase epithet, include those too. Authority = the
# rest.

_RANK_WORDS = {w.rstrip(".") for w in INFRA_CONNECTORS}


def split_name_and_authority(text: str) -> tuple[str, str, str, str]:
    """Split a cleaned entry text into (name, authority, infra_rank, infra_epithet).

    `name` is the binomial or trinomial without authority.
    `authority` is what follows. `infra_rank` / `infra_epithet` are filled when
    an infraspecific rank is present, otherwise blank.
    """
    text = norm_text(text)
    if not text:
        return "", "", "", ""
    # Drop hybrid markers embedded at start ("× Genus species") up-front so
    # we tokenize clean binomial first. strip_hybrid handles that later too.
    tokens = text.split(" ")
    # Genus = token[0] (may have leading × that we'll handle via strip_hybrid)
    if len(tokens) < 2:
        return text, "", "", ""
    genus = tokens[0]
    # Some genera may have the hybrid cross as the first token e.g. "×"
    species_idx = 1
    if genus in {"×", "x"}:
        # rare on this PDF but be safe
        if len(tokens) < 3:
            return text, "", "", ""
        genus = tokens[1]
        species_idx = 2
    if species_idx >= len(tokens):
        return text, "", "", ""
    species = tokens[species_idx]
    # Species should be all-lowercase-alpha-or-hyphen (allow trailing punct).
    stripped = species.rstrip(".,;").lower()
    if not re.match(r"^[a-z\-\u00ff]+$", stripped) and not species.startswith("×"):
        # Species token doesn't look like a species epithet — give up, keep
        # whole text as name.
        return text, "", "", ""

    name_parts = [genus, species]
    infra_rank = ""
    infra_epithet = ""

    # Check for infraspecific rank after the species.
    next_idx = species_idx + 1
    if next_idx + 1 < len(tokens):
        cand = tokens[next_idx].rstrip(".,").lower()
        if cand in _RANK_WORDS:
            infra_rank = tokens[next_idx]
            infra_epithet = tokens[next_idx + 1]
            name_parts.extend([tokens[next_idx], tokens[next_idx + 1]])
            next_idx += 2

    authority = " ".join(tokens[next_idx:]).strip()
    name = " ".join(name_parts).strip()
    return name, authority, infra_rank, infra_epithet


def parse_binomial_from_name(name: str) -> tuple[str, str]:
    """Pull (genus, species) out of a parsed name string."""
    if not name:
        return "", ""
    toks = name.split()
    if len(toks) < 2:
        return toks[0] if toks else "", ""
    genus = toks[0].lstrip("×").strip()
    species = toks[1].rstrip(".,").lower()
    return genus, species


# ----------------------------------------------------------------------------
# Genus-heading detection. A left-column bold-italic entry whose name portion
# is a single word (genus only, no species epithet) is a section heading, not
# an accepted species. Examples: "Aerangis Rchb.f.", "Bulbophyllum Thouars".
# We also skip bold-italic LEFT-COLUMN entries that *are* full binomials —
# they are cross-references (the same accepted name re-listed in the "all
# names" index at its alphabetical spot), already captured on the right.
# ----------------------------------------------------------------------------


def is_genus_heading(entry: Entry) -> bool:
    """A single-word bold-italic entry = genus header (e.g. 'Aerangis Rchb.f.')."""
    if entry.kind != "bolditalic":
        return False
    # Reconstruct "italic part" only — the CMBXTI10 spans. Authority is the
    # CMBX10 spans. If the italic text is a single word, it's a genus heading.
    italic_text = "".join(s["text"] for s in entry.spans if is_bold_italic_span(s))
    italic_text = norm_text(italic_text)
    # A full binomial has at least two italic tokens.
    return len(italic_text.split()) <= 1


# ----------------------------------------------------------------------------
# Pairing: for each left-column italic synonym entry, find the right-column
# bold-italic accepted entry whose y-range covers (or is nearest to) the
# synonym's y_start. Multiple synonyms can share the same accepted entry.
# ----------------------------------------------------------------------------


def pair_synonyms_to_accepted(
    left_entries: list[Entry],
    right_entries: list[Entry],
) -> list[tuple[Entry, Entry | None]]:
    """Return list of (synonym_entry, accepted_entry_or_None) pairings."""
    # Build a list of right entries sorted by y_start. For each left synonym
    # entry, pick the right entry with the largest y_start <= synonym.y_start
    # + small slack (so same-row pairings win).
    pairs: list[tuple[Entry, Entry | None]] = []
    right_sorted = sorted(right_entries, key=lambda e: e.y_start)
    for left in left_entries:
        if left.kind != "italic":
            continue
        # Find best match: same-y match preferred, else the most recent right
        # entry whose y_start <= left.y_start (the accepted name is printed
        # at or just above its stack of synonyms).
        best: Entry | None = None
        for r in right_sorted:
            if r.y_start <= left.y_start + ROW_Y_TOLERANCE:
                best = r
            else:
                break
        pairs.append((left, best))
    return pairs


# ----------------------------------------------------------------------------
# Main driver.
# ----------------------------------------------------------------------------


def clean_entry_text(entry: Entry) -> str:
    """Combine spans to text, strip dot-leaders and trailing page numbers."""
    raw = entry.combined_text()
    return clean_text_fragment(raw)


def make_row(
    synonym_entry: Entry,
    accepted_entry: Entry | None,
    idx_within_page: int,
) -> dict[str, str]:
    out = blank_row()

    syn_text = clean_entry_text(synonym_entry)
    syn_name, syn_auth, syn_rank, syn_infra = split_name_and_authority(syn_text)
    syn_name = strip_hybrid(syn_name)
    syn_genus, syn_species = parse_binomial_from_name(syn_name)

    if accepted_entry is not None:
        acc_text = clean_entry_text(accepted_entry)
        acc_name, acc_auth, _, _ = split_name_and_authority(acc_text)
        acc_name = strip_hybrid(acc_name)
        acc_genus, _ = parse_binomial_from_name(acc_name)
    else:
        acc_text = ""
        acc_name = ""
        acc_auth = ""
        acc_genus = ""

    syn_full = syn_text
    acc_full = acc_text

    page_num = synonym_entry.page
    y = synonym_entry.y_start
    out["source"] = "cites_pdf"
    out["source_record_id"] = f"p{page_num}_y{y:.1f}_{idx_within_page}"
    out["relation"] = "synonym_of"
    out["accepted_name"] = acc_name
    out["accepted_name_full"] = acc_full
    out["accepted_authority"] = acc_auth
    out["synonym_name"] = syn_name
    out["synonym_name_full"] = syn_full
    out["synonym_authority"] = syn_auth
    out["synonym_type"] = "Unknown"
    out["family"] = "Orchidaceae"
    out["genus"] = syn_genus
    out["species"] = syn_species
    out["infraspecific_rank"] = syn_rank.rstrip(".") if syn_rank else ""
    out["infraspecific_epithet"] = syn_infra

    extras = {"page": page_num, "y": round(y, 1)}
    if acc_genus and syn_genus and acc_genus != syn_genus:
        extras["accepted_genus"] = acc_genus
    out["raw_extras"] = pack_extras(extras)
    return out


def process_part_i(
    doc: pymupdf.Document,
    first_page: int,
    last_page: int,
) -> tuple[list[dict[str, str]], dict[str, int]]:
    """Walk the Part I pages, extract all synonym->accepted pairs."""
    all_rows: list[dict[str, str]] = []
    stats = {
        "pages_processed": 0,
        "italic_entries": 0,
        "bold_italic_entries_left": 0,
        "bold_italic_entries_right": 0,
        "genus_headings": 0,
        "pair_failures": 0,
        "authority_skipped": 0,
    }

    for pnum in range(first_page, last_page + 1):
        page = doc[pnum]
        spans = collect_spans(page)
        rows = group_into_rows(spans)
        left_entries = build_entries_for_column(rows, "left", pnum)
        right_entries = build_entries_for_column(rows, "right", pnum)

        # Collect stats.
        for e in left_entries:
            if e.kind == "italic":
                stats["italic_entries"] += 1
            elif e.kind == "bolditalic":
                stats["bold_italic_entries_left"] += 1
                if is_genus_heading(e):
                    stats["genus_headings"] += 1
        for e in right_entries:
            if e.kind == "bolditalic":
                stats["bold_italic_entries_right"] += 1

        pairs = pair_synonyms_to_accepted(left_entries, right_entries)
        for idx, (syn, acc) in enumerate(pairs):
            if acc is None or is_genus_heading(acc):
                # Pairing failed OR the "accepted" landed on a genus heading.
                stats["pair_failures"] += 1
                # Still emit a row with blank accepted for traceability? The
                # spec says every row must have non-empty accepted_name (see
                # validate_frame). So skip these rather than producing invalid
                # rows — but count them for the warning.
                continue
            row = make_row(syn, acc, idx)
            if not row["accepted_name"]:
                stats["pair_failures"] += 1
                continue
            if not row["accepted_authority"]:
                stats["authority_skipped"] += 1
            if not row["synonym_authority"]:
                stats["authority_skipped"] += 1
            all_rows.append(row)
        stats["pages_processed"] += 1

    return all_rows, stats


def main() -> None:
    if not INPUT_PATH.exists():
        raise FileNotFoundError(f"missing input PDF at {INPUT_PATH}")
    doc = pymupdf.open(INPUT_PATH)
    print(f"opened {INPUT_PATH.relative_to(PROJECT_ROOT)}: {len(doc)} pages")

    first, last = find_part_ranges(doc)
    print(f"detected Part I content pages: {first}..{last} (inclusive, 0-indexed)")
    print(f"  -> {last - first + 1} pages in Part I")

    rows, stats = process_part_i(doc, first, last)
    doc.close()

    print()
    print("extraction stats:")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    italic_total = stats["italic_entries"]
    failures = stats["pair_failures"]
    if italic_total:
        failure_rate = failures / italic_total
        print(f"  pairing_failure_rate: {failure_rate:.2%} ({failures}/{italic_total})")
        if failure_rate > 0.05:
            print("  !!! WARNING: pairing failure rate exceeds 5% — heuristics may need tuning.")

    df = pd.DataFrame(rows, columns=SCHEMA)
    print()
    print(f"built {len(df)} synonym->accepted rows")

    # Spot-check: 30 random samples.
    print()
    print("=== 30 random sample pairings ===")
    rng = random.Random(42)
    sample_indices = rng.sample(range(len(df)), k=min(30, len(df)))
    for i in sample_indices:
        r = df.iloc[i]
        # decode page from raw_extras isn't trivial — read source_record_id.
        src_id = r["source_record_id"]
        print(f"  {src_id}: {r['synonym_name_full']!r} -> {r['accepted_name_full']!r}")

    blank_acc = int((df["accepted_name"] == "").sum())
    blank_acc_auth = int((df["accepted_authority"] == "").sum())
    blank_syn_auth = int((df["synonym_authority"] == "").sum())
    print()
    print(f"rows with blank accepted_name: {blank_acc}")
    print(f"rows with blank accepted_authority: {blank_acc_auth}")
    print(f"rows with blank synonym_authority: {blank_syn_auth}")

    validate_frame(df)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)
    rel = OUTPUT_PATH.relative_to(PROJECT_ROOT)
    print()
    print(f"wrote {len(df)} rows to {rel}")


if __name__ == "__main__":
    main()
