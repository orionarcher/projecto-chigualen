"""Freeze what the Python resolver says, so the browser port can be held to it.

The static build has a second implementation of the logic that decides what a
name means (web/js/data.js). Two implementations of CITES-relevant semantics is
exactly how a species card and a batch export start disagreeing — the thing the
authority reported. This writes a fixture of Python verdicts; open
web/parity/ in a browser to check the JS against it.

    python3 tests/make_parity_fixture.py
"""

from __future__ import annotations

import json
import random
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# The resolver only needs streamlit for its cache decorators.
st = types.ModuleType("streamlit")
def _cache(*a, **k):
    def deco(fn):
        store = {}
        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            if key not in store:
                store[key] = fn(*args, **kwargs)
            return store[key]
        return wrapper
    return deco(a[0]) if a and callable(a[0]) else deco
st.cache_data = _cache
st.cache_resource = _cache
st.session_state = {}
sys.modules["streamlit"] = st

from app.data import SOURCES, build_search_index, resolve  # noqa: E402

OUT = ROOT / "web" / "parity" / "expected.json"
SAMPLE_PER_KIND = 400

# Cases worth pinning by hand: every contest class, the names the authority
# reported, an authority tail, a PDF ligature, and both failure modes.
HANDPICKED = [
    "Stelis ariasii", "Anathallis ariasii", "Vanda falcata", "Neofinetia falcata",
    "Oncidium isidrense", "Aerangis divitiflora", "Aerangis divitiﬂora",
    "Dracula chimaera (Rchb.f.) Luer", "  vanda   FALCATA  ",
    "Zzz nonexistent", "Cattleya", "", "Angraecum aﬃne",
]


def main() -> int:
    index = build_search_index()
    rng = random.Random(20260901)

    by_kind: dict[str, list[str]] = {"accepted": [], "synonym": [], "contested": []}
    for key, entry in index.items():
        by_kind.setdefault(entry["match_type"], []).append(key)

    names = list(HANDPICKED)
    for kind, keys in by_kind.items():
        names += [index[k]["canonical"] if kind != "synonym" else k
                  for k in rng.sample(keys, min(SAMPLE_PER_KIND, len(keys)))]
    # Synonym keys come back lowercased; feeding them in that shape also exercises
    # the normalizer on both sides.
    names = list(dict.fromkeys(names))

    cases = []
    for name in names:
        r = resolve(name, index)
        cases.append({
            "query": name,
            "binomial": r.binomial,
            "verdict": r.verdict,
            "acceptedName": r.accepted_name,
            "synonymType": r.synonym_type,
            "descriptionYear": r.description_year,
            "citesAppendix": r.cites_appendix,
            "contestClass": r.contest_class,
            "perSource": {
                s: [r.per_source[s].status, r.per_source[s].accepted_name]
                for s in SOURCES
            },
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"sources": SOURCES, "cases": cases},
                              ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    kinds = {}
    for c in cases:
        kinds[c["verdict"]] = kinds.get(c["verdict"], 0) + 1
    print(f"wrote {len(cases)} cases to {OUT.relative_to(ROOT)}")
    for k, n in sorted(kinds.items()):
        print(f"  {k:<14} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
