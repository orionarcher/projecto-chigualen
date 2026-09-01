/**
 * Browser port of app/data.py.
 *
 * This file is the risk in the static build: it is a SECOND implementation of
 * the logic that decides what a name means. The Streamlit app has exactly one
 * (`resolve()` in app/data.py), which is what guarantees a species card and a
 * batch export can never disagree. Here that guarantee has to be maintained by
 * hand, so every function below names the Python function it mirrors, and
 * web/js/parity.js re-runs the Python test fixtures against it.
 */

const KIND_ACCEPTED = 0, KIND_SYNONYM = 1, KIND_CONTESTED = 2;

export const STATUS = {
  ACCEPTED: 'accepted',
  SYNONYM: 'synonym',
  CONTESTED: 'contested',
  ABSENT: 'not_in_source',
};

let INDEX = null;
const shardCache = new Map();

// Resolve data paths against this module, not the page. web/parity/ sits at a
// different depth from web/index.html, and a deploy may live under a subpath.
const DATA = new URL('../data/', import.meta.url);
const dataUrl = (path) => new URL(path, DATA).href;

// ---------------------------------------------------------------- loading

export async function load(onProgress) {
  if (INDEX) return INDEX;
  const res = await fetch(dataUrl('index.json'));
  if (!res.ok) throw new Error(`index.json: HTTP ${res.status}`);

  // Stream so the loading bar reflects reality on a slow connection rather
  // than sitting at zero for the whole megabyte.
  const total = Number(res.headers.get('content-length')) || 0;
  const reader = onProgress ? res.body?.getReader() : null;
  let payload;
  if (reader) {
    const chunks = [];
    let received = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      received += value.length;
      onProgress(total ? received / total : null, received);
    }
    payload = JSON.parse(await new Blob(chunks).text());
  } else {
    payload = await res.json();
  }

  INDEX = payload;
  INDEX.keyPos = new Map();
  for (let i = 0; i < INDEX.keys.length; i++) INDEX.keyPos.set(INDEX.keys[i], i);
  return INDEX;
}

export const index = () => INDEX;

/** FNV-1a, 32-bit. Must stay identical to shard_of() in scripts/10_export_web.py. */
function shardOf(name) {
  let h = 0x811c9dc5;
  const s = name.toLowerCase();
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h % INDEX.shards;
}

async function fetchShard(kind, name) {
  const shard = String(shardOf(name)).padStart(3, '0');
  const key = `${kind}/${shard}`;
  if (!shardCache.has(key)) {
    shardCache.set(key, fetch(dataUrl(`${kind}/${shard}.json`)).then(r => (r.ok ? r.json() : {})));
  }
  return (await shardCache.get(key))[name] || null;
}

export const speciesRecord = (name) => fetchShard('species', name);
export const contestedRecord = (name) => fetchShard('contested', name);

// ------------------------------------------------------------ normalizing

// Mirrors _LIGATURES in scripts/_normalize.py. The CITES checklist is
// LaTeX-typeset, so pasted names really do contain U+FB01/U+FB02.
const LIGATURES = {
  'ﬀ': 'ff', 'ﬁ': 'fi', 'ﬂ': 'fl', 'ﬃ': 'ffi', 'ﬄ': 'ffl',
  'ﬅ': 'st', 'ﬆ': 'st', 'Ĳ': 'IJ', 'ĳ': 'ij',
  'Œ': 'OE', 'œ': 'oe', 'Æ': 'AE', 'æ': 'ae',
};

/** Mirrors norm_text() in scripts/_normalize.py. */
export function normText(value) {
  if (value === null || value === undefined) return '';
  let s = String(value);
  if (['nan', 'none'].includes(s.toLowerCase())) return '';
  s = s.normalize('NFC').replace(/[ﬀ-ﬆĲĳŒœÆæ]/g,
    (c) => LIGATURES[c] || c);
  return s.replace(/\s+/g, ' ').trim();
}

/** Mirrors normalize_query() in app/data.py. */
export function normalizeQuery(q) {
  const s = normText(q);
  if (!s) return '';
  const t = s.split(' ');
  if (t.length < 2) return '';
  const genus = t[0], species = t[1].toLowerCase();
  if (!genus || !species) return '';
  return genus.charAt(0).toUpperCase() + genus.slice(1).toLowerCase() + ' ' + species;
}

// ---------------------------------------------------------------- lookups

function entryFor(key) {
  const pos = INDEX.keyPos.get(key);
  return pos === undefined ? null : INDEX.entries[pos];
}

const sourcesFromMask = (mask) => INDEX.sources.filter((_, i) => mask & (1 << i));

/** Mirrors prefix_matches() in app/data.py, but ordered: the sorted key array
 *  makes a real prefix range available, which the Python dict scan could not do. */
export function prefixMatches(query, limit = 15) {
  const q = normText(query).toLowerCase();
  if (!q) return [];
  const keys = INDEX.keys;
  let lo = 0, hi = keys.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; keys[mid] < q ? (lo = mid + 1) : (hi = mid); }

  const out = [];
  for (let i = lo; i < keys.length && keys[i].startsWith(q) && out.length < limit; i++) {
    out.push(INDEX.names[INDEX.entries[i][1]] === undefined ? keys[i] : displayName(i));
  }
  if (out.length >= limit) return dedupe(out, limit);

  // Fall back to substring, as the Streamlit version does.
  for (let i = 0; i < keys.length && out.length < limit; i++) {
    if (!keys[i].startsWith(q) && keys[i].includes(q)) out.push(displayName(i));
  }
  return dedupe(out, limit);
}

function displayName(i) {
  const [kind, target] = INDEX.entries[i];
  // A synonym is offered under its own spelling; selecting it redirects, which
  // is what the Streamlit app does via the redirect banner.
  return kind === KIND_SYNONYM ? titleCase(INDEX.keys[i]) : INDEX.names[target];
}

const titleCase = (s) => s.charAt(0).toUpperCase() + s.slice(1);

function dedupe(list, limit) {
  const seen = new Set(), out = [];
  for (const n of list) { if (!seen.has(n)) { seen.add(n); out.push(n); } if (out.length >= limit) break; }
  return out;
}

// --------------------------------------------------------------- resolve

/**
 * Mirrors resolve() in app/data.py, verdict for verdict.
 * Returns { query, binomial, verdict, acceptedName, synonymType, descriptionYear,
 *           citesAppendix, contestClass, note, perSource: {src: {status, acceptedName, detail}} }
 */
export function resolve(query) {
  const blank = () => Object.fromEntries(
    INDEX.sources.map(s => [s, { status: STATUS.ABSENT, acceptedName: '', detail: '' }]));

  const binomial = normalizeQuery(query);
  if (!binomial) {
    return { query, binomial: '', verdict: 'unparseable', acceptedName: '', synonymType: '',
             descriptionYear: '', citesAppendix: '', contestClass: '',
             note: 'fewer than 2 tokens or empty', perSource: blank() };
  }

  const res = { query, binomial, verdict: 'missing', acceptedName: '', synonymType: '',
                descriptionYear: '', citesAppendix: '', contestClass: '', note: '',
                perSource: blank() };

  const entry = entryFor(binomial.toLowerCase());
  if (!entry) {
    res.note = 'no source in this build records this binomial';
    return res;
  }

  const [kind, target, mask, extra] = entry;

  if (kind === KIND_CONTESTED) {
    res.verdict = 'contested';
    res.contestClass = INDEX.contestClasses[extra] || '';
    // Per-source detail lives in a shard, so this synchronous path can only
    // report the class. Anything that needs the per-source verdict — the
    // species card, the batch export — must use resolveFull().
    return res;
  }

  const scalars = INDEX.speciesScalars[String(target)];
  if (scalars) {
    res.descriptionYear = scalars[0] || '';
    res.citesAppendix = INDEX.appendices[scalars[1]] || '';
  }

  if (kind === KIND_SYNONYM) {
    res.verdict = 'synonym';
    res.acceptedName = INDEX.names[target];
    res.synonymType = INDEX.synTypes[extra] || '';
    const pairSources = sourcesFromMask(mask);
    const parentEntry = entryFor(res.acceptedName.toLowerCase());
    const parentSources = parentEntry ? sourcesFromMask(parentEntry[2]) : [];
    for (const s of INDEX.sources) {
      if (pairSources.includes(s)) {
        res.perSource[s] = { status: STATUS.SYNONYM, acceptedName: res.acceptedName,
                             detail: res.synonymType };
      } else if (parentSources.includes(s)) {
        res.perSource[s] = { status: STATUS.ABSENT, acceptedName: '',
                             detail: `knows ${res.acceptedName}, not this name` };
      }
    }
    return res;
  }

  res.verdict = 'accepted';
  res.acceptedName = INDEX.names[target];
  for (const s of sourcesFromMask(mask)) {
    res.perSource[s] = { status: STATUS.ACCEPTED, acceptedName: res.acceptedName, detail: '' };
  }
  return res;
}

/** resolve(), plus the per-source detail that needs a shard fetch. */
export async function resolveFull(query) {
  const res = resolve(query);
  if (res.verdict !== 'contested') return res;
  const rec = await contestedRecord(res.binomial);
  if (!rec) return res;
  res.contestClass = rec.contestClass;
  res.note = rec.reason;
  res.contestReason = rec.reason;
  res.contestedRows = rec.rows;
  for (const row of rec.rows) {
    const rel = row.source_says_relation || '';
    const parent = (row.source_says_accepted_parent || '').split('|')[0];
    if (rel === 'accepted+synonym_of') {
      res.perSource[row.source] = { status: STATUS.CONTESTED, acceptedName: parent,
                                    detail: `accepted, and also a synonym of ${parent}` };
    } else if (rel.startsWith('accepted')) {
      res.perSource[row.source] = { status: STATUS.ACCEPTED, acceptedName: res.binomial,
                                    detail: row.evidence || '' };
    } else {
      res.perSource[row.source] = { status: STATUS.SYNONYM, acceptedName: parent,
                                    detail: row.synonym_type || '' };
    }
  }
  return res;
}

/** Mirrors parse_synonyms_detailed() in app/data.py. */
export function parseSynonymsDetailed(detail) {
  if (!detail) return [];
  const parts = detail.split('], ');
  return parts.map((p, i) => {
    if (i < parts.length - 1) p += ']';
    const lb = p.lastIndexOf(' [');
    if (lb < 0 || !p.endsWith(']')) return { name: p, type: '', sources: '' };
    const name = p.slice(0, lb).trim();
    const meta = p.slice(lb + 2, -1);
    const semi = meta.indexOf(';');
    return semi < 0
      ? { name, type: meta.trim(), sources: '' }
      : { name, type: meta.slice(0, semi).trim(), sources: meta.slice(semi + 1).trim() };
  }).filter(r => r.name);
}
