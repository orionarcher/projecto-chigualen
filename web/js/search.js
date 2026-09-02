/** Search page: query, results, species card, contested view.
 *  Browser port of app/search.py. */
import * as data from './data.js';
import { el, esc, chip, sourceChips, sourceColour, perSourcePanel, table } from './ui.js';

const TYPE_COLOURS = {
  Homotypic: '#2e7d32', Heterotypic: '#ad1457', 'Orthographic variant': '#6d4c41',
  Nomenclatural: '#455a64', Mixed: '#ef6c00', Unknown: '#8b98a9',
};
const CITES_COLOURS = { I: '#b71c1c', II: '#ef6c00', III: '#f9a825' };

const CONTEST_HEADLINE = {
  status_conflict: 'Sources disagree about whether this name is accepted at all.',
  parent_conflict: 'Every source calls this a synonym — of different species.',
  parent_contested: 'This name is not itself disputed; the species it belongs to is.',
};

let root, resultsEl, detailEl, inputEl;
let active = -1;      // highlighted suggestion, -1 = none
let current = [];     // suggestions currently on screen

const KIND_LABEL = ['accepted', 'synonym', 'contested'];
const KIND_COLOUR = ['var(--accepted)', 'var(--synonym)', 'var(--contested)'];
const TIER_NOTE = ['', '', '', 'matched on the epithet', 'matched inside the name', 'closest spelling'];

export function render(container, initialQuery = '') {
  const idx = data.index();
  container.innerHTML = '';
  root = el(`<div>
    <h1>Search orchids</h1>
    <p class="caption">Start typing an accepted name or a synonym — matches appear as
      you go. The consolidated database has ${idx.counts.species.toLocaleString()}
      accepted species and ${idx.counts.synonymPairs.toLocaleString()} synonym pairs
      across ${idx.sources.length} sources.</p>
    <div class="combo">
      <label for="q">Search by name</label>
      <input type="text" id="q" placeholder="e.g. Dracula chimaera" autocomplete="off"
        spellcheck="false" role="combobox" aria-expanded="false" aria-controls="results"
        aria-autocomplete="list">
      <ul class="results" id="results" role="listbox" hidden></ul>
    </div>
    <div id="detail"></div>
  </div>`);
  container.appendChild(root);

  inputEl = root.querySelector('#q');
  resultsEl = root.querySelector('#results');
  detailEl = root.querySelector('#detail');

  inputEl.addEventListener('input', () => showMatches(inputEl.value));
  inputEl.addEventListener('keydown', onKeyDown);
  inputEl.addEventListener('focus', () => { if (inputEl.value.trim()) showMatches(inputEl.value); });
  document.addEventListener('click', (e) => { if (!root.contains(e.target)) closeList(); });

  if (initialQuery) { inputEl.value = initialQuery; showMatches(initialQuery, true); }
  inputEl.focus();
}

function closeList() {
  resultsEl.hidden = true;
  inputEl.setAttribute('aria-expanded', 'false');
  active = -1;
}

function onKeyDown(ev) {
  if (resultsEl.hidden || !current.length) {
    if (ev.key === 'Enter' && inputEl.value.trim()) { showMatches(inputEl.value, true); }
    return;
  }
  if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
    ev.preventDefault();
    active = ev.key === 'ArrowDown'
      ? (active + 1) % current.length
      : (active <= 0 ? current.length : active) - 1;
    paintActive();
  } else if (ev.key === 'Enter') {
    ev.preventDefault();
    // No arrow pressed yet: Enter takes the top match, which is what makes the
    // box feel predictive rather than like a form field.
    pick(current[active >= 0 ? active : 0]);
  } else if (ev.key === 'Escape') {
    closeList();
  }
}

function paintActive() {
  [...resultsEl.children].forEach((li, i) => {
    const on = i === active;
    li.firstElementChild.classList.toggle('on', on);
    li.setAttribute('aria-selected', on ? 'true' : 'false');
    if (on) li.scrollIntoView({ block: 'nearest' });
  });
}

function pick(s) {
  if (!s) return;
  inputEl.value = s.name;
  closeList();
  open(s.name);
}

/** Bold the part of the name the query actually matched. */
function markUp(s) {
  const name = s.name;
  if (!s.highlight) return esc(name);
  const [start, len] = s.highlight;
  if (start >= name.length) return esc(name);
  return esc(name.slice(0, start)) + '<b class="hit">' +
         esc(name.slice(start, start + len)) + '</b>' + esc(name.slice(start + len));
}

function showMatches(query, openTop = false) {
  const q = query.trim();
  if (!q) { current = []; closeList(); detailEl.innerHTML = ''; return; }

  current = data.suggest(q, 12);
  if (!current.length) {
    resultsEl.hidden = false;
    inputEl.setAttribute('aria-expanded', 'true');
    resultsEl.innerHTML = `<li class="muted empty">No name like “${esc(q)}”.
      Try the species epithet on its own — the genus may have changed.</li>`;
    return;
  }

  resultsEl.innerHTML = current.map((s, i) => {
    const detail = s.kind === 1 ? `synonym of <span class="sci">${esc(s.canonical)}</span>`
                 : s.kind === 2 ? 'contested'
                 : 'accepted';
    return `<li role="option" aria-selected="false"><button data-i="${i}">
      <span class="sci">${markUp(s)}</span>
      <span class="kind" style="color:${KIND_COLOUR[s.kind]}">${detail}</span>
      ${TIER_NOTE[s.tier] ? `<span class="why">${TIER_NOTE[s.tier]}</span>` : ''}
    </button></li>`;
  }).join('');
  resultsEl.hidden = false;
  inputEl.setAttribute('aria-expanded', 'true');
  active = -1;

  resultsEl.querySelectorAll('button').forEach(b =>
    b.addEventListener('click', () => pick(current[Number(b.dataset.i)])));

  // An unambiguous, fully-typed name opens straight away.
  const exact = current[0] && current[0].tier === 0;
  if (openTop || exact) { closeList(); open(current[0].name); }
}

export async function open(name) {
  detailEl.innerHTML = '<p class="muted">Loading…</p>';
  const res = await data.resolveFull(name);

  if (res.verdict === 'contested') return renderContested(res);
  if (res.verdict === 'missing' || res.verdict === 'unparseable') {
    detailEl.innerHTML = `<div class="banner warn">Nothing in the database for
      <span class="sci">${esc(name)}</span>.</div>`;
    return;
  }
  const record = await data.speciesRecord(res.acceptedName);
  if (!record) {
    detailEl.innerHTML = `<div class="banner error">Could not load the record for
      <span class="sci">${esc(res.acceptedName)}</span>.</div>`;
    return;
  }
  renderCard(res, record, res.verdict === 'synonym' ? name : null);
}

function goto(name) {
  inputEl.value = name;
  closeList();
  open(name);
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function renderContested(res) {
  const rules = data.index().contestRules || {};
  const parents = [];
  for (const row of res.contestedRows || []) {
    for (const p of (row.source_says_accepted_parent || '').split('|')) {
      if (p.trim() && !parents.includes(p.trim())) parents.push(p.trim());
    }
  }
  detailEl.innerHTML = `
    <div class="banner error">
      <h4>⚠ Contested name — <code>${esc(res.contestClass || 'contested')}</code></h4>
      <span class="sci">${esc(res.binomial)}</span> is held out of the consolidated
      database because the sources cannot be reconciled on it.
    </div>
    ${res.contestClass in CONTEST_HEADLINE
      ? `<p><b>${esc(CONTEST_HEADLINE[res.contestClass])}</b></p>` : ''}
    ${res.contestReason ? `<p>Here, specifically: ${esc(res.contestReason)}.</p>` : ''}
    ${rules[res.contestClass] ? `<details class="panel"><summary>How this class is decided</summary>
      <p>${esc(rules[res.contestClass])}</p>
      <p class="muted">A disagreement about homotypic vs heterotypic typing never
      produces a contested name.</p></details>` : ''}
    ${parents.length ? `<h3>Species the sources place this name in</h3>
      <div id="parents">${parents.map(p =>
        `<button class="linkish" data-goto="${esc(p)}">→ <span class="sci">${esc(p)}</span></button>`
      ).join(' &nbsp; ')}</div>` : ''}
    <h3>Per-source detail</h3>
    ${table(['Source', 'Says', 'Accepted parent', 'Authority', 'Type', 'Evidence'],
      (res.contestedRows || []).map(r => [
        chip(r.source, sourceColour(r.source)),
        esc(r.source_says_relation || ''),
        `<span class="sci">${esc(r.source_says_accepted_parent || '')}</span>`,
        esc(r.authority || ''), esc(r.synonym_type || ''),
        `<span class="muted">${esc(r.evidence || '')}</span>`,
      ]))}
    ${perSourcePanel(res)}`;
  detailEl.querySelectorAll('[data-goto]').forEach(b =>
    b.addEventListener('click', () => goto(b.dataset.goto)));
}

function renderCard(res, rec, redirectedFrom) {
  const name = res.acceptedName;
  const badges = [];
  if (rec.cites_appendix) badges.push(chip(`CITES ${rec.cites_appendix}`,
    CITES_COLOURS[rec.cites_appendix] || '#8b98a9'));
  if (rec.description_year) badges.push(chip(`described ${rec.description_year}`, '#8b98a9'));
  const srcCount = (rec.sources || '').split(',').filter(s => s.trim()).length;
  badges.push(chip(`${srcCount} source${srcCount === 1 ? '' : 's'}`, '#8b98a9'));

  const syns = data.parseSynonymsDetailed(rec.synonyms_detailed || '');
  badges.push(chip(`${syns.length} synonym${syns.length === 1 ? '' : 's'}`, '#8b98a9'));
  const disputed = (rec.contested_synonyms || '').split(',').map(s => s.trim()).filter(Boolean);
  if (disputed.length) badges.push(chip(`${disputed.length} disputed`, 'var(--contested)'));

  const kv = (label, value) => value ? `<div class="kv"><b>${label}:</b> ${esc(value)}</div>` : '';

  detailEl.innerHTML = `
    ${redirectedFrom ? `<div class="banner info">↻ Redirected from synonym
      <span class="sci">${esc(redirectedFrom)}</span>
      ${chip(res.synonymType || 'Unknown', TYPE_COLOURS[res.synonymType] || '#8b98a9')}
      ${sourceChips(Object.entries(res.perSource)
        .filter(([, v]) => v.status === 'synonym').map(([s]) => s).join(','))}</div>` : ''}
    <h2 class="sci">${esc(name)}</h2>
    ${rec.accepted_name_full && rec.accepted_name_full !== name
      ? `<div class="caption">${esc(rec.accepted_name_full)}</div>` : ''}
    <div>${badges.join('')}</div>
    <div style="margin:12px 0"><b class="muted">Sources:</b> ${sourceChips(rec.sources)}</div>

    ${syns.length ? `<h3>Synonyms</h3>
      ${syns.some(s => s.type === 'Mixed') ? `<p class="muted"><code>Mixed</code> means
        sources agree the name is a synonym of this species but disagree on homotypic
        vs heterotypic — a typing disagreement, not a contested name.</p>` : ''}
      ${table(['Synonym', 'Type', 'Sources'], syns.map(s => [
        `<span class="sci">${esc(s.name)}</span>`,
        chip(s.type || 'Unknown', TYPE_COLOURS[s.type] || '#8b98a9'),
        sourceChips(s.sources)]))}` : ''}

    ${disputed.length ? `<h3>Disputed names filed here</h3>
      <p class="caption">${disputed.length} name${disputed.length === 1 ? '' : 's'} that at
        least one source places under <span class="sci">${esc(name)}</span>, but which the
        sources disagree on. They are <b>not</b> in the synonym list above and <b>not</b> in
        the consolidated database — open one to see who says what.</p>
      <div>${disputed.map(d =>
        `<button class="linkish" data-goto="${esc(d)}">→ <span class="sci">${esc(d)}</span></button>`
      ).join(' &nbsp; ')}</div>` : ''}

    <div class="grid2" style="margin-top:26px">
      <div><h3 style="margin-top:0">Taxonomy</h3>
        ${kv('Family', rec.family)}${kv('Genus', rec.genus)}
        ${kv('Species epithet', rec.species)}${kv('Rank', rec.taxon_rank)}
        ${kv('Basionym ID', rec.basionym)}</div>
      <div><h3 style="margin-top:0">Publication</h3>
        ${kv('Authority', rec.accepted_authority)}${kv('Description year', rec.description_year)}
        ${kv('First published', rec.first_published)}${kv('Place', rec.place_of_publication)}</div>
    </div>

    ${rec.geographic_area ? `<h3>Distribution</h3><ul>${
      rec.geographic_area.split(';').map(p => p.trim()).filter(Boolean)
        .map(p => `<li>${esc(p)}</li>`).join('')}</ul>` : ''}

    ${perSourcePanel(res)}

    <h3>External</h3>
    ${[rec.wcvp_ipni_id ? `<a href="https://powo.science.kew.org/results?q=${encodeURIComponent(rec.wcvp_ipni_id)}" target="_blank" rel="noopener">POWO</a>` : '',
       rec.wfo_taxon_id ? `<a href="https://www.worldfloraonline.org/taxon/${encodeURIComponent(rec.wfo_taxon_id)}" target="_blank" rel="noopener">World Flora Online</a>` : '']
      .filter(Boolean).join(' &nbsp;•&nbsp; ') || '<span class="muted">none</span>'}`;

  detailEl.querySelectorAll('[data-goto]').forEach(b =>
    b.addEventListener('click', () => goto(b.dataset.goto)));
}
