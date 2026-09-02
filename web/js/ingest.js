/** Batch diff: upload an authority CSV, resolve every row, export per-source
 *  columns. Browser port of app/ingest.py.
 *
 *  The whole point of the static build: the uploaded checklist is parsed and
 *  resolved in the page. It is never sent anywhere. */
import * as data from './data.js';
import * as backbone from './backbone.js';
import { el, esc, table } from './dom.js';
import { parseCsv, downloadCsv } from './csv.js';

// Colours live in css/style.css as .cat-<key>; see the CSP note there.
const CATEGORIES = [
  ['matched_accepted', 'Matched (accepted)'],
  ['matched_synonym',  'Matched (synonym)'],
  ['contested',        'Contested'],
  ['missing',          'Missing'],
  ['unparseable',      'Unparseable'],
];
const VERDICT_TO_CATEGORY = {
  accepted: 'matched_accepted', synonym: 'matched_synonym',
  contested: 'contested', missing: 'missing', unparseable: 'unparseable',
};

export function render(container) {
  container.innerHTML = '';
  const root = el(`<div>
    <h1>Ingest an authority CSV</h1>
    <p class="caption">Compare an external list against the consolidated database.
      <b>The file never leaves your browser</b> — it is parsed and resolved in this page,
      with no server involved.</p>
    <label for="file">Upload CSV or TSV. Required: a column containing the species name.</label>
    <input type="file" id="file" accept=".csv,.tsv,.txt">
    <div id="map"></div>
    <div id="out"></div>
  </div>`);
  container.appendChild(root);

  const mapEl = root.querySelector('#map'), outEl = root.querySelector('#out');
  root.querySelector('#file').addEventListener('change', async (ev) => {
    const file = ev.target.files?.[0];
    outEl.innerHTML = '';
    if (!file) { mapEl.innerHTML = ''; return; }
    const { headers, records } = parseCsv(await file.text());
    if (!records.length) { mapEl.innerHTML = '<div class="banner warn">File parsed but has no rows.</div>'; return; }

    const guess = headers.findIndex(h => /scientific|species_name|taxon|name/i.test(h));
    mapEl.innerHTML = `
      <div class="panel">
        <b>${esc(file.name)}</b> — ${records.length.toLocaleString()} rows,
        ${headers.length} columns
        <label for="namecol">Name column</label>
        <select id="namecol">${headers.map((h, i) =>
          `<option${i === Math.max(guess, 0) ? ' selected' : ''}>${esc(h)}</option>`).join('')}</select>
        <label for="label">Authority name (for the report filename)</label>
        <input type="text" id="label" placeholder="e.g. Sander's List 2024">
        ${Object.keys(backbone.registered()).length
          ? `<p class="muted">Your checklists will each get a column pair too:
              ${Object.keys(backbone.registered()).map(id =>
                `<code>${esc(id)}_status</code>`).join(', ')}.</p>`
          : `<p class="muted">Tip: load your own backbone on the
              <b>Your own checklists</b> page and it gets its own columns here too.</p>`}
        <p></p><button class="primary" id="go">Analyze</button>
      </div>`;
    mapEl.querySelector('#go').addEventListener('click', () => {
      const col = mapEl.querySelector('#namecol').value;
      const label = mapEl.querySelector('#label').value.trim();
      analyze(records, col, label, outEl);
    });
  });
}

/** Mirrors build_report() in app/ingest.py.
 *
 *  Async because a contested name's per-source verdict lives in a shard, not in
 *  the index. Resolving those synchronously would silently export
 *  `not_in_source` for all five sources on exactly the rows an authority most
 *  needs the detail for. The shard cache dedupes, so a 5,000-row list costs at
 *  most one fetch per shard actually touched. */
export async function buildReport(records, nameCol) {
  // Warm every contested shard first, in parallel, so the map below is not a
  // waterfall of one round trip per row.
  const contested = new Set();
  for (const rec of records) {
    const quick = data.resolve(rec[nameCol] ?? '');
    if (quick.verdict === 'contested') contested.add(quick.binomial);
  }
  await Promise.all([...contested].map(n => data.contestedRecord(n)));

  return Promise.all(records.map(async rec => {
    const res = await data.resolveFull(rec[nameCol] ?? '');
    const row = {
      ...rec,
      diff_category: VERDICT_TO_CATEGORY[res.verdict] || res.verdict,
      normalized_binomial: res.binomial,
      matched_accepted_name: res.acceptedName,
      synonym_type: res.synonymType,
      description_year: res.descriptionYear,
      cites_appendix: res.citesAppendix,
      contest_class: res.contestClass,
      contest_reason: res.contestReason || '',
      match_notes: res.note,
    };
    for (const s of data.index().sources) {
      row[`${s}_status`] = res.perSource[s].status;
      row[`${s}_accepted_name`] = res.perSource[s].acceptedName;
    }
    // Loaded checklists get the same column pair, so an authority can diff a list
    // against its own backbone and the five built-in sources in one pass.
    for (const [id, bb] of Object.entries(backbone.registered())) {
      const v = backbone.lookup(bb, res.binomial);
      row[`${id}_status`] = v.status;
      row[`${id}_accepted_name`] = v.acceptedName;
    }
    return row;
  }));
}

async function analyze(records, nameCol, label, outEl) {
  outEl.innerHTML = '<p class="muted">Resolving…</p>';
  const t0 = performance.now();
  const report = await buildReport(records, nameCol);
  const ms = Math.round(performance.now() - t0);

  const counts = {};
  for (const r of report) counts[r.diff_category] = (counts[r.diff_category] || 0) + 1;
  const base = (label || 'authority').replace(/\s+/g, '_').toLowerCase();
  const srcs = [...data.index().sources, ...Object.keys(backbone.registered())];

  outEl.innerHTML = `
    <h3>Diff summary — ${esc(label || 'authority')} (${report.length.toLocaleString()} rows)</h3>
    <div class="stats">${CATEGORIES.map(([k, l]) => `
      <div class="stat cat-${k}">
        <div class="n">${counts[k] || 0}</div>
        <div class="l">${l}</div></div>`).join('')}</div>
    <p class="muted">Resolved in ${ms} ms, entirely in this browser tab.
      Every row carries <code>contest_class</code>, <code>contest_reason</code>,
      <code>description_year</code> and a <code>_status</code> / <code>_accepted_name</code>
      pair for each of: ${srcs.map(s => `<code>${esc(s)}</code>`).join(', ')}.</p>
    <p><button class="primary" id="dl">Download full diff CSV</button></p>
    <div id="panels"></div>`;

  outEl.querySelector('#dl').addEventListener('click', () =>
    downloadCsv(`summary_${base}.csv`, report));

  const panels = outEl.querySelector('#panels');
  for (const [key, title] of CATEGORIES) {
    const subset = report.filter(r => r.diff_category === key);
    if (!subset.length) continue;
    const cols = ['normalized_binomial', 'matched_accepted_name', 'description_year',
                  'contest_class', 'contest_reason']
      .filter(c => subset.some(r => r[c]));
    const det = el(`<details class="panel">
      <summary><b>${esc(title)}</b> · ${subset.length.toLocaleString()}</summary>
      <div class="mt-sm">
        ${table([nameCol, ...cols], subset.slice(0, 200).map(r =>
          [`<span class="sci">${esc(r[nameCol])}</span>`, ...cols.map(c => esc(r[c] || ''))]))}
        ${subset.length > 200 ? `<p class="muted">Showing the first 200 of
          ${subset.length.toLocaleString()} — the download has them all.</p>` : ''}
        <p><button class="primary" data-dl="${esc(key)}">Download ${esc(key)} CSV</button></p>
      </div></details>`);
    panels.appendChild(det);
    det.querySelector('[data-dl]').addEventListener('click', () =>
      downloadCsv(`${key}_${base}.csv`, subset));
  }
}
