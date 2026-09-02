# Static build

The same database as the Streamlit app in [`../app`](../app), served as a static
site. **There is no server.** The pipeline output is packed into JSON at build
time and every lookup, diff and export runs in the visitor's browser.

## Why it exists

Three things this shape buys that the hosted Python app cannot:

- **An authority's checklist never leaves their machine.** The Streamlit app
  says uploads are never written to disk, which is true — but the file still
  travels to a server. Here it is parsed and resolved in the page. That matters
  for a CITES Management Authority diffing an internal list.
- **Longevity.** A folder of files on a CDN keeps working with no runtime to
  deprecate, no process to keep alive and no bill to lapse.
- **Anyone can self-host it.** It is static files; other authorities can drop
  the folder behind their own web server.

## How the data is shaped

`scripts/10_export_web.py` turns `Chigualen/data/out/*.csv` into:

| | Size | Fetched |
|---|---|---|
| `data/index.json` | 4.5 MB raw, **~1.0 MB gzipped** | once, before first paint |
| `data/species/NNN.json` | 256 shards, ~13 kB gzipped each | when a species card opens |
| `data/contested/NNN.json` | 256 shards, ~4 kB gzipped each | when a contested name opens |

The index holds every binomial the database knows with just enough to resolve
it, so **search and the whole batch diff run with no further network access** —
5,000 names resolve in about 250 ms. Only the verbose per-record detail is
sharded. Shards are keyed by FNV-1a hash rather than by initial, because an
alphabetical split puts a tenth of Orchidaceae in `B` alone.

`data/` is generated, not committed. Netlify rebuilds it on every deploy
(~5 s); to work on the site locally:

```bash
pip install -r requirements-web.txt
python3 scripts/10_export_web.py
python3 scripts/serve_web.py
```

Then open <http://localhost:8610>. Opening `index.html` from the filesystem will
not work — browsers block `fetch` on `file://`.

**Use `scripts/serve_web.py`, not `python3 -m http.server`.** It reads the header
block out of `netlify.toml` and sends it, so the strict Content-Security-Policy
applies locally. Plain `http.server` sends no CSP at all, which is how the first
deploy went out with every colour stripped: the CSP has no `'unsafe-inline'`,
and the UI was colouring chips through `style` attributes. The same gap hid a
second bug — the parity page's inline `<script>` never ran in production. Both
are fixed, and both were invisible until the local server started sending the
real headers.

### Caching

`/data/*` is served `immutable` for a year, which is only safe because the URLs
carry a build stamp. `scripts/10_export_web.py` hashes `index.json` into
`web/build.json`, and `js/data.js` reads that first and appends `?v=<id>` to
every data request. The URL therefore changes exactly when the data changes, and
not otherwise. Without it, `immutable` would pin every returning visitor to
whichever version of the database they happened to load first — a rebuilt
pipeline would simply never reach them.

Code carries no such stamp, so `/js/*` and `/css/*` revalidate
(`max-age=0, must-revalidate`). They are a few kB and ETag makes the usual case
a 304. An earlier `max-age=3600` here meant a deploy took up to an hour to
reach anyone who had already visited — which is exactly how the first CSP fix
appeared not to work.

`css/sources.css` is generated but lives under `/css/`, not `/data/`, precisely
so it revalidates: it has no build stamp on its URL.

### Working within the CSP

`default-src 'self'` with no `'unsafe-inline'` for either scripts or styles.
Practically:

- **No `style="…"` in generated HTML.** Colour through classes. Fixed
  vocabularies (synonym types, CITES appendices, per-source status, diff
  categories) live in `css/style.css`; per-source colours are generated into
  `data/sources.css` from `scripts/_sources.py`, so adding a source still means
  editing one registry entry.
- **No inline `<script>`.** Modules only, loaded with `src`.
- Assigning `element.style.width` from JS is fine — CSSOM is not covered by CSP.
  Only attributes and `<style>`/`<script>` elements are.

This is worth keeping strict rather than adding `'unsafe-inline'`: the reason
this build exists is that an uploaded checklist cannot leave the browser, and a
policy that permits inline injection is a weaker guarantee of that.

## The search box

Suggestions appear from the first character, ranked by how literally the query
matched. Five ways in, tried cheapest first:

| | Query | Finds |
|---|---|---|
| exact | `dracula chimaera` | opens straight away |
| name prefix | `stelis ar` | Stelis ariasii, arrecta, arbuscula… |
| genus + epithet prefix | `van fal` | Vanda falcata |
| epithet alone | `falcata` | Vanda falcata, Stenia falcata… |
| substring | `ariasii` | Stelis ariasii, Ida ariasii… |
| within one or two typos | `anathalis ariasi` | Anathallis ariasii, marked *closest spelling* |

**Matching on the epithet alone matters more here than in most search boxes.**
This database exists because genera keep changing: someone reading an older
permit knows the epithet and has a genus that has since been sunk, which is
precisely the case a plain prefix search cannot help with.

The substring and typo passes only run when the literal ones turned up fewer
than three hits, so a well-formed query never pays for them. Typing costs
1–20 ms per keystroke on the full 79k-name index; the epithet ordering is built
once on idle after first paint rather than on the first character typed.

Arrow keys move through the list, Enter takes the highlighted row (or the top
one, if you have not moved), Escape closes it.

Ranking is *tier, then accepted before synonym before contested, then shorter
name, then alphabetical* — so a name that is current outranks one that is not.

## The parity check

`web/js/data.js` is a **second implementation** of the logic that decides what a
name means. The Streamlit app has exactly one (`resolve()` in `app/data.py`),
which is what guarantees a species card and a batch export can never disagree —
the failure the CITES authority reported. Two implementations put that guarantee
at risk.

The mitigation is <http://localhost:8610/parity/>. `tests/make_parity_fixture.py`
freezes what the Python resolver says about 1,213 cases — every contest class,
both reported bugs, authority tails, PDF ligatures, and a seeded random sample
across accepted, synonym and contested names — and the page re-runs all of them
through the browser resolver, comparing every field including per-source
verdicts.

**Run it after touching either resolver.** It currently passes 1,213/1,213.

## Your own checklists

A checklist is parsed in the page and kept in `sessionStorage`, so a reload does
not lose it and closing the tab discards it. The Streamlit version keeps it in
server-side session state, which means the file is uploaded first; here it never
leaves the tab.

Once loaded it behaves like a built-in source: its own row in the per-source
panel on every species card, its own `<id>_status` / `<id>_accepted_name` pair in
the batch export, and a callout wherever it disagrees with the consolidated
result. Column auto-mapping guesses across English, German, Spanish and French
headings, since WISIA — the case this page exists for — is German.

A checklist too large for the ~5 MB session-storage quota still loads; it says
so, and will not survive a reload.

## One registry, four consumers

Everything factual on the Data sources page — what each source is authoritative
for, what it cannot tell you, the `cites_csv`/`cites_pdf` distinction, the
`contest_class` definitions — comes from `data/sources.json`, exported straight
from `scripts/_sources.py`.

That registry is now the single definition for all four consumers:
`06_consolidate.py` which assigns a contest class, `09_repair_outputs.py` which
backfills it, `app/sources_page.py` which explains it, and this build's export.
They had drifted into three separate copies. Only the narrative around the facts
is written twice.

## What is not ported

Nothing, as of this build. The Streamlit app still has its original plain-prefix
search rather than the typeahead described above — search ranking is
presentation, deliberately outside the resolver the two implementations must
agree on, so they are allowed to differ.

## Module layout

```
dom.js       rendering helpers, no imports
csv.js       RFC-4180 parse + download, no imports
data.js      index loading, resolve(), suggest()
backbone.js  your own checklists          → data, csv, dom
ui.js        per-source panel             → data, backbone, dom
search.js    search, species card         → data, dom, ui
ingest.js    batch diff                   → data, backbone, dom, csv
sources.js   data sources page            → dom, backbone
app.js       shell and router
```

Deliberately a DAG. `ui.js` needs `backbone.js` for the per-source panel, and
`backbone.js` needs rendering helpers and CSV parsing — which is why those live
in `dom.js` and `csv.js` rather than in `ui.js` and `ingest.js`. ES modules
tolerate cycles, but only until someone reads an imported binding during module
evaluation instead of inside a function.
