"""Custom taxonomic backbones — bring your own checklist.

CITES Management and Scientific Authorities maintain their own name lists (the
German authority's WISIA database, for example). This module lets one be
uploaded and then treated exactly like a built-in source: it gets its own column
in the batch export, its own verdict on the species card, and its own row in the
per-source comparison.

Backbones live in `st.session_state` only. Nothing is written to disk, and they
disappear when the browser session ends — the app stays read-only.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import pandas as pd
import streamlit as st

from app.data import (
    STATUS_ABSENT,
    STATUS_ACCEPTED,
    STATUS_SYNONYM,
    SourceVerdict,
    normalize_query,
)

SESSION_KEY = "custom_backbones"

# Values in a status column that mean "this is the current name here". Anything
# else that is not obviously a synonym marker is reported verbatim.
ACCEPTED_WORDS = {"accepted", "accepted name", "valid", "current", "a", "yes", "1", "true"}
SYNONYM_WORDS = {"synonym", "syn", "synonym of", "s", "heterotypic", "homotypic",
                 "heterotypic synonym", "homotypic synonym", "not accepted"}


@dataclass
class Backbone:
    id: str
    label: str
    entries: dict[str, dict] = field(default_factory=dict)  # lowercased binomial → record
    n_rows: int = 0
    n_unparseable: int = 0
    has_status: bool = False
    has_accepted: bool = False

    @property
    def n_names(self) -> int:
        return len(self.entries)

    def lookup(self, binomial: str) -> SourceVerdict:
        """What this backbone says about a binomial."""
        if not binomial:
            return SourceVerdict()
        rec = self.entries.get(binomial.lower())
        if rec is None:
            return SourceVerdict()
        return SourceVerdict(
            status=rec["status"],
            accepted_name=rec["accepted_name"],
            detail=rec["raw_status"],
        )

    def reverse_synonyms(self, accepted_name: str) -> list[str]:
        """Names this backbone files under `accepted_name` — useful for spotting
        synonyms the authority recognises that the consolidated DB does not."""
        if not accepted_name:
            return []
        target = accepted_name.lower()
        return sorted(
            rec["name"] for rec in self.entries.values()
            if rec["status"] == STATUS_SYNONYM and rec["accepted_name"].lower() == target
        )


def _classify(raw_status: str, name: str, accepted_name: str) -> tuple[str, str]:
    """(status, accepted_name) for one uploaded row."""
    status_word = raw_status.strip().lower()
    if accepted_name and accepted_name.lower() != name.lower():
        return STATUS_SYNONYM, accepted_name
    if status_word in SYNONYM_WORDS:
        # Declared a synonym but no parent given — we can say it is not current
        # here, but not what replaces it.
        return STATUS_SYNONYM, accepted_name
    if status_word in ACCEPTED_WORDS or not status_word:
        return STATUS_ACCEPTED, name
    # Unrecognised vocabulary: report it rather than guessing.
    return STATUS_ACCEPTED, accepted_name or name


def build_backbone(
    backbone_id: str,
    label: str,
    df: pd.DataFrame,
    name_col: str,
    status_col: str | None = None,
    accepted_col: str | None = None,
) -> Backbone:
    bb = Backbone(
        id=backbone_id,
        label=label,
        n_rows=len(df),
        has_status=bool(status_col),
        has_accepted=bool(accepted_col),
    )
    for rec in df.to_dict("records"):
        name = normalize_query(str(rec.get(name_col, "")))
        if not name:
            bb.n_unparseable += 1
            continue
        raw_status = str(rec.get(status_col, "")) if status_col else ""
        accepted = normalize_query(str(rec.get(accepted_col, ""))) if accepted_col else ""
        status, accepted_name = _classify(raw_status, name, accepted)
        # First row wins, so a checklist that repeats a name keeps its first verdict.
        bb.entries.setdefault(name.lower(), {
            "name": name,
            "status": status,
            "accepted_name": accepted_name,
            "raw_status": raw_status.strip(),
        })
    return bb


# --------------------------------------------------------------------------
# Session storage
# --------------------------------------------------------------------------

def registered() -> dict[str, Backbone]:
    return st.session_state.setdefault(SESSION_KEY, {})


def register(bb: Backbone) -> None:
    registered()[bb.id] = bb


def unregister(backbone_id: str) -> None:
    registered().pop(backbone_id, None)


def verdicts_for(binomial: str) -> dict[str, SourceVerdict]:
    """Every registered backbone's verdict on a binomial, keyed by backbone id."""
    return {bb.id: bb.lookup(binomial) for bb in registered().values()}


def slugify(label: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in label).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "checklist"


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------

def _read_upload(file) -> pd.DataFrame:
    raw = file.read()
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("Could not decode file as UTF-8 or Latin-1.")
    df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    if df.shape[1] == 1:
        alt = pd.read_csv(io.StringIO(text), sep="\t", dtype=str, keep_default_na=False)
        if alt.shape[1] > 1:
            df = alt
    return df


NONE_CHOICE = "— (none) —"


def render() -> None:
    st.title("Your own checklists")
    st.markdown(
        """
Load a taxonomic backbone of your own — an authority's internal database such as
**WISIA**, a national checklist, a nursery register — and it is compared
alongside WCVP, WFO and the two CITES sources everywhere in the app:

- it gets **its own verdict** on every species card,
- it gets **its own `_status` and `_accepted_name` columns** in the batch export,
- names where it disagrees with the consolidated database are called out.

Checklists live in this browser session only. Nothing is uploaded anywhere or
written to disk, and they are gone when you close the tab.
        """
    )

    existing = registered()
    if existing:
        st.subheader("Loaded checklists")
        for bb in list(existing.values()):
            c1, c2 = st.columns([5, 1])
            with c1:
                st.markdown(
                    f"**{bb.label}** &nbsp; `{bb.id}` — {bb.n_names:,} usable names "
                    f"from {bb.n_rows:,} rows"
                    + (f" · {bb.n_unparseable:,} unparseable" if bb.n_unparseable else "")
                    + (" · with status column" if bb.has_status else "")
                    + (" · with accepted-name column" if bb.has_accepted else "")
                )
            with c2:
                if st.button("Remove", key=f"rm_{bb.id}"):
                    unregister(bb.id)
                    st.rerun()
        st.divider()

    st.subheader("Add a checklist")
    uploaded = st.file_uploader(
        "CSV or TSV. One row per name; a name column is required.",
        type=["csv", "tsv", "txt"],
        key="backbone_upload",
    )
    if uploaded is None:
        st.info(
            "Expected shape: a column of scientific names, optionally a status "
            "column (`accepted` / `synonym`) and a column giving the accepted "
            "name for synonyms. Authority strings after the binomial are fine — "
            "they are stripped."
        )
        return

    try:
        df = _read_upload(uploaded)
    except Exception as e:  # noqa: BLE001 — user-facing error path
        st.error(f"Could not read file: {e}")
        return
    if df.empty:
        st.warning("File parsed but has no rows.")
        return

    st.dataframe(df.head(8), use_container_width=True)

    label = st.text_input(
        "Name for this checklist", value=uploaded.name.rsplit(".", 1)[0],
        help="Used as the column prefix in exports and the label on species cards.",
    )
    cols = [NONE_CHOICE] + list(df.columns)
    name_default = 1
    for i, c in enumerate(df.columns, start=1):
        if any(k in c.lower() for k in ("scientific", "species_name", "taxon", "name")):
            name_default = i
            break
    c1, c2, c3 = st.columns(3)
    with c1:
        name_col = st.selectbox("Name column (required)", cols, index=name_default)
    with c2:
        status_col = st.selectbox("Status column (optional)", cols, index=0)
    with c3:
        accepted_col = st.selectbox("Accepted-name column (optional)", cols, index=0)

    if name_col == NONE_CHOICE:
        st.warning("Map a name column to continue.")
        return

    if st.button("Load checklist", type="primary"):
        bb = build_backbone(
            backbone_id=slugify(label),
            label=label.strip() or "checklist",
            df=df,
            name_col=name_col,
            status_col=None if status_col == NONE_CHOICE else status_col,
            accepted_col=None if accepted_col == NONE_CHOICE else accepted_col,
        )
        if not bb.entries:
            st.error("No usable binomials found in that column.")
            return
        register(bb)
        st.success(
            f"Loaded **{bb.label}** — {bb.n_names:,} names. It now appears on "
            f"species cards and in batch exports as `{bb.id}_status` / "
            f"`{bb.id}_accepted_name`."
        )
        st.rerun()
