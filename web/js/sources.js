/** Data sources page: what each source is, and how conflicts are decided.
 *  Browser port of app/sources_page.py.
 *
 *  Everything factual comes from data/sources.json, exported from
 *  scripts/_sources.py — the same registry the Streamlit page renders and the
 *  consolidation classifies against. Internal ids (`cites_csv` and friends) are
 *  export column prefixes; they are not names, and do not appear here as names. */

import { el, esc, table, chip } from './dom.js';
import { dataUrl } from './data.js';
import * as backbone from './backbone.js';

const KIND_LABEL = {
  backbone: 'Taxonomic backbone',
  regulatory: 'Regulatory source',
  curated: 'Curated by the project team',
};

let payload = null;

/** Very small subset of markdown: *italic*, **bold**, `code`, [text](url).
 *  The registry prose is written for Streamlit, which renders markdown. */
function md(text) {
  return esc(text)
    .replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g,
      (_, t, u) => `<a href="${u}" target="_blank" rel="noopener">${t}</a>`)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
    .replace(/\*([^*]+)\*/g, '<i class="sci">$1</i>');
}

function sourceCard(s) {
  const meta = [
    `<div><b>Edition used:</b> ${md(s.edition)}</div>`,
    `<div><b>Terms of use:</b> ${esc(s.licence)}</div>`,
    `<div><b>Covers:</b> ${s.speciesTouched.toLocaleString()} of the species in this database</div>`,
    s.homepage
      ? `<div><a href="${esc(s.homepage)}" target="_blank" rel="noopener">Source homepage</a></div>`
      : '',
  ].filter(Boolean).join('');

  return `<div class="panel source-card">
    <div class="eyebrow">${esc(KIND_LABEL[s.kind] || s.kind)}</div>
    <h3>${esc(s.label)}</h3>
    <p class="one-liner">${md(s.oneLiner)}</p>
    ${s.provenanceConfirmed ? '' : `<div class="banner warn">The exact provenance of
      this file is inferred from its columns rather than from a documented export —
      worth confirming with the project team before citing it.</div>`}
    <div class="grid2">
      <div><h4>Authoritative for</h4>
        <ul>${s.contributes.map(i => `<li>${md(i)}</li>`).join('')}</ul></div>
      <div><h4>Does not carry</h4>
        <ul>${s.doesNotCarry.map(i => `<li>${md(i)}</li>`).join('')}</ul></div>
    </div>
    <h4 class="mt-sm">Where it comes from</h4>
    <p>${md(s.origin)}</p>
    ${s.notes ? `<div class="banner info">${md(s.notes)}</div>` : ''}
    <div class="meta">${meta}</div>
  </div>`;
}

export async function render(container) {
  container.innerHTML = '<p class="muted">Loading source descriptions…</p>';
  if (!payload) {
    // Must go through dataUrl(): /data/* is cached immutably for a year, and only
    // the build stamp it appends makes that safe. Fetching the bare path pins the
    // reader to whichever version of this page they saw first.
    payload = await fetch(dataUrl('sources.json')).then(r => r.json());
  }
  const p = payload;
  const custom = Object.values(backbone.registered());

  container.innerHTML = '';
  container.appendChild(el(`<div>
    <h1>Data sources</h1>
    <p class="lede">Five sources go into this database. They are not
      interchangeable: two describe taxonomy, two describe regulation, and one
      supplies the synonym typing the others cannot. Where they disagree, the name
      is held back rather than resolved silently.</p>

    <div class="section">Every source in detail</div>
    ${p.sources.map(sourceCard).join('')}

    <div class="section">Your own reference lists</div>
    ${custom.length
      ? `<p class="section-intro">Loaded in this browser tab and compared alongside
          the five above.</p>
         <ul>${custom.map(bb => `<li><b>${esc(bb.label)}</b> —
          ${backbone.nameCount(bb).toLocaleString()} names</li>`).join('')}</ul>`
      : `<p class="section-intro">You can load a checklist of your own — an
          authority database such as WISIA, or any list of names — and it is
          compared alongside these five everywhere in the app. See
          <b>Your reference lists</b>.</p>`}

    <div class="section">How contested names are classified</div>
    <p class="section-intro">When the sources cannot be reconciled on a name, it is
      kept out of the main database and recorded separately, one row per source, so
      you can see who said what. The <b>Contest Class</b> records which comparison
      failed.</p>
    <div class="panel">
      ${p.contestClasses.map(c => `<div class="rule-row">
        <div>
          <div class="rule-name">${esc(c.title)}</div>
          <div class="rule-count">${(p.contestClassCounts[c.id] || 0).toLocaleString()} names</div>
        </div>
        <div>
          <div>${md(c.summary)}</div>
          <p class="rule-how">${md(c.detail)}</p>
          <p class="rule-eg muted">${md(c.example)}</p>
        </div>
      </div>`).join('')}
    </div>
    <div class="banner info">${md(p.typingNeverContests)}</div>

    <div class="section">What is in this build</div>
    <div class="stats">
      <div class="stat plain"><div class="n">${p.counts.species.toLocaleString()}</div>
        <div class="l">Accepted species</div></div>
      <div class="stat plain"><div class="n">${p.counts.synonymPairs.toLocaleString()}</div>
        <div class="l">Synonym pairs</div></div>
      <div class="stat plain"><div class="n">${p.counts.contested.toLocaleString()}</div>
        <div class="l">Contested names</div></div>
      <div class="stat plain"><div class="n">${p.counts.withYear.toLocaleString()}</div>
        <div class="l">With a description year</div></div>
    </div>
    ${table(['Source', 'Kind', 'Species covered', 'Terms of use'],
      p.sources.map(s => [
        `${chip(s.short, 'src-' + s.id)} ${esc(s.label)}`,
        esc(KIND_LABEL[s.kind] || s.kind),
        s.speciesTouched.toLocaleString(),
        esc(s.licence)]))}
  </div>`));
}
