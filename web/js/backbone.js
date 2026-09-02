/** Custom taxonomic backbones — bring your own checklist.
 *  Browser port of app/backbone.py.
 *
 *  CITES Management and Scientific Authorities keep their own name lists (the
 *  German authority's WISIA database, for instance). A loaded checklist is
 *  treated like a built-in source: its own verdict on every species card, its
 *  own columns in the batch export.
 *
 *  In the Streamlit app these live in server-side session state, which means the
 *  file is uploaded. Here they never leave the tab: parsed in the page and kept
 *  in sessionStorage, so a reload does not lose them and closing the tab does.
 */

import { STATUS, normalizeQuery } from './data.js';
import { parseCsv } from './csv.js';
import { el, esc, table } from './dom.js';

const STORE_KEY = 'chigualen.backbones';

// Status words that mean "this is the current name here". Anything unrecognised
// is reported verbatim rather than guessed at.
const ACCEPTED_WORDS = new Set(['accepted', 'accepted name', 'valid', 'current', 'a', 'yes', '1', 'true']);
const SYNONYM_WORDS = new Set(['synonym', 'syn', 'synonym of', 's', 'heterotypic', 'homotypic',
  'heterotypic synonym', 'homotypic synonym', 'not accepted']);

let loaded = null;   // id → {id, label, entries, nRows, nUnparseable, hasStatus, hasAccepted}

// ---------------------------------------------------------------- storage

function read() {
  if (loaded) return loaded;
  loaded = {};
  try {
    const raw = sessionStorage.getItem(STORE_KEY);
    if (raw) loaded = JSON.parse(raw);
  } catch { /* private mode, or a quota-cleared store — start empty */ }
  return loaded;
}

function write() {
  try {
    sessionStorage.setItem(STORE_KEY, JSON.stringify(loaded));
    return true;
  } catch {
    // A national checklist can exceed the ~5 MB sessionStorage quota. Keeping it
    // in memory is still correct; it just will not survive a reload.
    return false;
  }
}

export const registered = () => read();
export const count = () => Object.keys(read()).length;

export function unregister(id) {
  delete read()[id];
  write();
}

// --------------------------------------------------------------- building

function classify(rawStatus, name, acceptedName) {
  const word = (rawStatus || '').trim().toLowerCase();
  if (acceptedName && acceptedName.toLowerCase() !== name.toLowerCase()) {
    return [STATUS.SYNONYM, acceptedName];
  }
  if (SYNONYM_WORDS.has(word)) return [STATUS.SYNONYM, acceptedName || ''];
  if (ACCEPTED_WORDS.has(word) || !word) return [STATUS.ACCEPTED, name];
  return [STATUS.ACCEPTED, acceptedName || name];
}

export function build(id, label, records, nameCol, statusCol, acceptedCol) {
  const bb = {
    id, label, entries: {}, nRows: records.length, nUnparseable: 0,
    hasStatus: Boolean(statusCol), hasAccepted: Boolean(acceptedCol),
  };
  for (const rec of records) {
    const name = normalizeQuery(String(rec[nameCol] ?? ''));
    if (!name) { bb.nUnparseable++; continue; }
    const rawStatus = statusCol ? String(rec[statusCol] ?? '') : '';
    const accepted = acceptedCol ? normalizeQuery(String(rec[acceptedCol] ?? '')) : '';
    const [status, acceptedName] = classify(rawStatus, name, accepted);
    const key = name.toLowerCase();
    // First row wins, so a checklist that repeats a name keeps its first verdict.
    if (!(key in bb.entries)) {
      bb.entries[key] = { name, status, acceptedName, rawStatus: rawStatus.trim() };
    }
  }
  return bb;
}

export function register(bb) {
  read()[bb.id] = bb;
  return write();
}

export const slugify = (label) =>
  (label.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || 'checklist');

export const nameCount = (bb) => Object.keys(bb.entries).length;

// --------------------------------------------------------------- lookups

/** What one checklist says about a binomial. */
export function lookup(bb, binomial) {
  if (!binomial) return { status: STATUS.ABSENT, acceptedName: '', detail: '' };
  const rec = bb.entries[binomial.toLowerCase()];
  if (!rec) return { status: STATUS.ABSENT, acceptedName: '', detail: '' };
  return { status: rec.status, acceptedName: rec.acceptedName, detail: rec.rawStatus };
}

/** Every loaded checklist's verdict, keyed by checklist id. */
export function verdictsFor(binomial) {
  const out = {};
  for (const [id, bb] of Object.entries(read())) out[id] = lookup(bb, binomial);
  return out;
}

/** Names a checklist files under `acceptedName` — synonyms the authority
 *  recognises that the consolidated database may not. */
export function reverseSynonyms(bb, acceptedName) {
  if (!acceptedName) return [];
  const target = acceptedName.toLowerCase();
  return Object.values(bb.entries)
    .filter(r => r.status === STATUS.SYNONYM && r.acceptedName.toLowerCase() === target)
    .map(r => r.name)
    .sort();
}

// ------------------------------------------------------------------ page

const NONE = '— (none) —';

export function render(container) {
  container.innerHTML = '';
  const root = el(`<div>
    <h1>Your own checklists</h1>
    <p>Load a taxonomic backbone of your own — an authority's internal database
      such as <b>WISIA</b>, a national checklist, a nursery register — and it is
      compared alongside WCVP, WFO and the two CITES sources everywhere in the app:</p>
    <ul>
      <li>its own <b>verdict</b> on every species card,</li>
      <li>its own <b>_status</b> and <b>_accepted_name</b> columns in the batch export,</li>
      <li>names where it disagrees with the consolidated database are called out.</li>
    </ul>
    <p class="muted">Checklists are parsed in this browser tab and kept only in
      its session storage. Nothing is uploaded anywhere and nothing is written to
      disk; closing the tab discards them.</p>
    <div id="loaded"></div>
    <h3>Add a checklist</h3>
    <label for="bbfile">CSV or TSV. One row per name; a name column is required.</label>
    <input type="file" id="bbfile" accept=".csv,.tsv,.txt">
    <div id="bbmap"></div>
  </div>`);
  container.appendChild(root);

  paintLoaded(root.querySelector('#loaded'), container);

  const mapEl = root.querySelector('#bbmap');
  root.querySelector('#bbfile').addEventListener('change', async (ev) => {
    const file = ev.target.files?.[0];
    if (!file) { mapEl.innerHTML = ''; return; }
    const { headers, records } = parseCsv(await file.text());
    if (!records.length) {
      mapEl.innerHTML = '<div class="banner warn">File parsed but has no rows.</div>';
      return;
    }
    // The authorities most likely to load a checklist here do not all work in
    // English — WISIA, the case this page exists for, is German. Guess across a
    // few languages; the dropdowns are there when the guess is wrong.
    const guessName = headers.findIndex(h =>
      /scientific|species_name|taxon|name|wissenschaftlich|nombre|nom_|espece|especie/i.test(h));
    const guessStatus = headers.findIndex(h => /status|statut|estado|rang/i.test(h));
    const guessAccepted = headers.findIndex(h =>
      /accepted|current|valid|akzept|g(ü|ue)ltig|correct|aceptado|accept/i.test(h));
    const opts = (sel) => [NONE, ...headers]
      .map((h, i) => `<option${i === sel + 1 ? ' selected' : ''}>${esc(h)}</option>`).join('');

    mapEl.innerHTML = `<div class="panel">
      <b>${esc(file.name)}</b> — ${records.length.toLocaleString()} rows, ${headers.length} columns
      <label for="bblabel">Name for this checklist</label>
      <input type="text" id="bblabel" value="${esc(file.name.replace(/\.[^.]+$/, ''))}">
      <div class="grid2">
        <div>
          <label for="bbname">Name column (required)</label>
          <select id="bbname">${opts(Math.max(guessName, 0))}</select>
          <label for="bbstatus">Status column (optional)</label>
          <select id="bbstatus">${opts(guessStatus)}</select>
        </div>
        <div>
          <label for="bbaccepted">Accepted-name column (optional)</label>
          <select id="bbaccepted">${opts(guessAccepted)}</select>
          <p class="muted mt-sm">A status column lets the checklist say a name is
            <i>not</i> current; an accepted-name column lets it say what replaces it.
            Authority strings after the binomial are fine — they are stripped.</p>
        </div>
      </div>
      <p></p><button class="primary" id="bbgo">Load checklist</button>
      <div id="bbresult"></div>
    </div>`;

    mapEl.querySelector('#bbgo').addEventListener('click', () => {
      const label = mapEl.querySelector('#bblabel').value.trim() || 'checklist';
      const pick = (id) => {
        const v = mapEl.querySelector(id).value;
        return v === NONE ? null : v;
      };
      const nameCol = pick('#bbname');
      if (!nameCol) {
        mapEl.querySelector('#bbresult').innerHTML =
          '<div class="banner warn">Map a name column to continue.</div>';
        return;
      }
      const bb = build(slugify(label), label, records, nameCol, pick('#bbstatus'), pick('#bbaccepted'));
      if (!nameCount(bb)) {
        mapEl.querySelector('#bbresult').innerHTML =
          '<div class="banner error">No usable binomials found in that column.</div>';
        return;
      }
      const persisted = register(bb);
      mapEl.innerHTML = '';
      root.querySelector('#bbfile').value = '';
      paintLoaded(root.querySelector('#loaded'), container);
      root.querySelector('#loaded').insertAdjacentHTML('afterbegin',
        `<div class="banner info">Loaded <b>${esc(bb.label)}</b> —
          ${nameCount(bb).toLocaleString()} names. It now appears on species cards
          and in batch exports as <code>${esc(bb.id)}_status</code> /
          <code>${esc(bb.id)}_accepted_name</code>.
          ${persisted ? '' : '<br><b>Too large to keep in session storage</b> — it is ' +
            'loaded for this page view but will be lost on reload.'}</div>`);
    });
  });
}

function paintLoaded(host, container) {
  const all = Object.values(read());
  if (!all.length) {
    host.innerHTML = `<div class="banner info">No checklists loaded. Expected shape:
      a column of scientific names, optionally a status column
      (<code>accepted</code> / <code>synonym</code>) and a column giving the
      accepted name for synonyms.</div>`;
    return;
  }
  host.innerHTML = `<h3>Loaded checklists</h3>${table(
    ['Checklist', 'Column prefix', 'Usable names', 'Rows read', 'Columns mapped', ''],
    all.map(bb => [
      `<b>${esc(bb.label)}</b>`,
      `<code>${esc(bb.id)}</code>`,
      nameCount(bb).toLocaleString(),
      bb.nRows.toLocaleString() + (bb.nUnparseable
        ? ` <span class="muted">(${bb.nUnparseable.toLocaleString()} unparseable)</span>` : ''),
      [bb.hasStatus ? 'status' : null, bb.hasAccepted ? 'accepted name' : null]
        .filter(Boolean).join(', ') || '<span class="muted">name only</span>',
      `<button class="linkish" data-rm="${esc(bb.id)}">remove</button>`,
    ]))}`;
  host.querySelectorAll('[data-rm]').forEach(b =>
    b.addEventListener('click', () => { unregister(b.dataset.rm); render(container); }));
}
