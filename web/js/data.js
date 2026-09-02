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
const BUILD_URL = new URL('../build.json', DATA);

// Data files keep the same names across deploys, so they are cached hard and
// busted by a build id instead. Without this, `immutable` would mean a rebuilt
// database never reaches anyone who has visited before.
let BUILD = '';
export const dataUrl = (path) =>
  new URL(path + (BUILD ? (path.includes('?') ? '&' : '?') + 'v=' + BUILD : ''), DATA).href;

// ---------------------------------------------------------------- loading

export async function load(onProgress) {
  if (INDEX) return INDEX;

  // build.json is small and deliberately uncached; everything it points at is
  // then safe to cache for a year.
  BUILD = await fetch(BUILD_URL.href, { cache: 'no-cache' })
    .then(r => (r.ok ? r.json() : {}))
    .then(b => b.build || '')
    .catch(() => '');

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

// --------------------------------------------------------- suggestions

/*
 * Typeahead. Five ways a query can hit, tried cheapest first and scored so the
 * most literal interpretation wins:
 *
 *   0  exact binomial
 *   1  prefix of the whole name           "stelis ar"  → Stelis ariasii
 *   2  genus prefix + epithet prefix      "van fal"    → Vanda falcata
 *   3  prefix of the epithet alone        "falcata"    → Vanda falcata
 *   4  substring anywhere                 "ariasii"    → Stelis ariasii
 *   5  within one or two typos            "anathalis"  → Anathallis ariasii
 *
 * (3) matters more here than in most search boxes: this database exists because
 * genera keep changing. Somebody reading an old permit knows the epithet and has
 * the wrong genus, which is exactly the case a plain prefix search cannot help
 * with. (5) matters because names get typed off paper.
 */

let epithets = null;      // epithet of each key, parallel to INDEX.keys
let byEpithet = null;     // key indices ordered by epithet
let genusEnd = null;      // index of the space in each key

/** Built on first search, not at load — it costs ~100 ms and nothing on first
 *  paint needs it. */
function ensureEpithetIndex() {
  if (byEpithet) return;
  const keys = INDEX.keys, n = keys.length;
  epithets = new Array(n);
  genusEnd = new Int32Array(n);
  for (let i = 0; i < n; i++) {
    const sp = keys[i].indexOf(' ');
    genusEnd[i] = sp;
    epithets[i] = sp < 0 ? keys[i] : keys[i].slice(sp + 1);
  }
  byEpithet = new Uint32Array(n);
  for (let i = 0; i < n; i++) byEpithet[i] = i;
  byEpithet.sort((a, b) => (epithets[a] < epithets[b] ? -1 : epithets[a] > epithets[b] ? 1 : a - b));
}

/** First position in a sorted string array whose value is >= q. */
function lowerBound(arr, q) {
  let lo = 0, hi = arr.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (arr[mid] < q) lo = mid + 1; else hi = mid; }
  return lo;
}

/** Same, over an array of indices read through `valueAt`. */
function lowerBoundBy(order, q, valueAt) {
  let lo = 0, hi = order.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (valueAt(order[mid]) < q) lo = mid + 1; else hi = mid; }
  return lo;
}

/** Damerau-Levenshtein, abandoned as soon as it cannot come in under `max`. */
function withinTypos(a, b, max) {
  const al = a.length, bl = b.length;
  if (Math.abs(al - bl) > max) return false;
  let prev = new Array(bl + 1), cur = new Array(bl + 1), prev2 = new Array(bl + 1);
  for (let j = 0; j <= bl; j++) prev[j] = j;
  for (let i = 1; i <= al; i++) {
    cur[0] = i;
    let best = cur[0];
    const lo = Math.max(1, i - max), hi = Math.min(bl, i + max);
    for (let j = 1; j <= bl; j++) cur[j] = Infinity;
    for (let j = lo; j <= hi; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      let v = Math.min(cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost);
      // transposition — 'aroasii' vs 'ariasii'
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
        v = Math.min(v, prev2[j - 2] + 1);
      }
      cur[j] = v;
      if (v < best) best = v;
    }
    if (best > max) return false;
    const spare = prev2; prev2 = prev; prev = cur; cur = spare;
  }
  return prev[bl] <= max;
}

const titleCase = (s) => s.charAt(0).toUpperCase() + s.slice(1);

const KIND_RANK = [0, 1, 2];  // accepted, then synonym, then contested

/**
 * @returns [{ name, key, kind, canonical, tier, highlight: [start, len] | null }]
 */
export function suggest(query, limit = 12) {
  const raw = normText(query).toLowerCase();
  if (!raw) return [];
  ensureEpithetIndex();

  const keys = INDEX.keys;
  const best = new Map();                       // key index → tier
  const marks = new Map();                      // key index → [start, len]
  const note = (i, tier, hl) => {
    if (!best.has(i) || best.get(i) > tier) { best.set(i, tier); if (hl) marks.set(i, hl); }
  };

  const tokens = raw.split(' ').filter(Boolean);
  const exact = normalizeQuery(query).toLowerCase();
  const CAP = 2000;   // enough to rank well; stops a one-letter query walking 10k keys

  // 0 / 1 — whole-name prefix, straight off the sorted key array.
  for (let i = lowerBound(keys, raw), n = 0;
       i < keys.length && keys[i].startsWith(raw) && n < CAP; i++, n++) {
    note(i, keys[i] === exact ? 0 : 1, [0, raw.length]);
  }

  // 2 — "van fal": genus prefix plus epithet prefix.
  if (tokens.length >= 2) {
    const [g, e] = tokens;
    for (let i = lowerBound(keys, g), n = 0;
         i < keys.length && keys[i].startsWith(g) && n < CAP; i++, n++) {
      if (epithets[i].startsWith(e)) note(i, 2, [genusEnd[i] + 1, e.length]);
    }
  }

  // 3 — epithet prefix, for when the genus has moved since the name was written.
  if (tokens.length === 1) {
    for (let p = lowerBoundBy(byEpithet, raw, (k) => epithets[k]), n = 0;
         p < byEpithet.length && epithets[byEpithet[p]].startsWith(raw) && n < CAP; p++, n++) {
      const i = byEpithet[p];
      note(i, 3, [genusEnd[i] + 1, raw.length]);
    }
  }

  // 4 — substring anywhere. Skipped for very short queries, where it would match
  // most of the database and tell the reader nothing.
  const RESCUE_BELOW = 3;
  if (best.size < RESCUE_BELOW && raw.length >= 3) {
    for (let i = 0; i < keys.length; i++) {
      if (best.has(i)) continue;
      const at = keys[i].indexOf(raw);
      if (at > 0) note(i, 4, [at, raw.length]);
    }
  }

  // 5 — typos. Bounded to keys sharing the first character: a first-letter typo
  // is rare, and the binary-searched range turns a 79k-way edit distance into a
  // few thousand.
  const maxTypos = raw.length >= 8 ? 2 : raw.length >= 5 ? 1 : 0;
  if (best.size < RESCUE_BELOW && maxTypos) {
    const first = raw[0];
    const lo = lowerBound(keys, first);
    for (let i = lo; i < keys.length && keys[i][0] === first; i++) {
      if (best.has(i)) continue;
      const against = tokens.length > 1 ? keys[i] : keys[i].slice(0, genusEnd[i]);
      if (withinTypos(raw, against, maxTypos)) note(i, 5, null);
    }
  }

  const out = [...best.entries()].map(([i, tier]) => {
    const [kind, target] = INDEX.entries[i];
    return {
      i, tier, kind,
      key: keys[i],
      name: kind === KIND_SYNONYM ? titleCase(keys[i]) : INDEX.names[target],
      canonical: INDEX.names[target],
      highlight: marks.get(i) || null,
    };
  });

  out.sort((a, b) =>
    a.tier - b.tier ||
    KIND_RANK[a.kind] - KIND_RANK[b.kind] ||
    a.key.length - b.key.length ||
    (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));

  return out.slice(0, limit);
}

/** Build the epithet index ahead of the first keystroke.
 *  It costs ~100 ms, which is invisible while the reader is looking at the page
 *  but very visible if it lands on the first character they type. */
export function warmSearch() { ensureEpithetIndex(); }

/** Kept for callers that only want names. */
export const prefixMatches = (query, limit = 15) => suggest(query, limit).map(s => s.name);

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
