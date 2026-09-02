/** Data sources page: what each source is, and how conflicts are decided.
 *  Browser port of app/sources_page.py.
 *
 *  Everything factual here comes from data/sources.json, exported straight from
 *  scripts/_sources.py — the same registry the Streamlit page renders and the
 *  consolidation classifies against. Only the narrative around it is written
 *  twice. */

import { el, esc, table, chip } from './dom.js';
import * as backbone from './backbone.js';

const KIND_LABEL = {
  backbone: 'Taxonomic backbone',
  regulatory: 'Regulatory',
  curated: 'Curated by the project team',
  custom: 'Your own checklist',
};

const CLASS_CHIP = {
  status_conflict: 'cat-contested',
  parent_conflict: 'cat-contested',
  parent_contested: 'ty-mixed',
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
    `<b>Edition used:</b> ${md(s.edition)}`,
    `<b>Licence / terms:</b> ${esc(s.licence)}`,
    `<b>Row types:</b> ${s.relations.map(r => `<code>${esc(r)}</code>`).join(', ')}`,
    s.cleaner ? `<b>Cleaner:</b> <code>${esc(s.cleaner)}</code>` : '',
    s.homepage ? `<a href="${esc(s.homepage)}" target="_blank" rel="noopener">Homepage</a>` : '',
  ].filter(Boolean);

  return `<div class="panel">
    <h3 class="mt-0">${esc(s.label)} <code>${esc(s.id)}</code></h3>
    <div class="src-kind ${esc('src-' + s.id)}">${esc(KIND_LABEL[s.kind] || s.kind)}</div>
    <p><i>${md(s.oneLiner)}</i></p>
    ${s.provenanceConfirmed ? '' : `<div class="banner warn">The exact provenance of
      this file is inferred from its columns rather than from a documented export —
      worth confirming with the project team before citing it.</div>`}
    <div class="grid2">
      <div><b>Authoritative for</b>
        <ul>${s.contributes.map(i => `<li>${md(i)}</li>`).join('')}</ul></div>
      <div><b>Does <i>not</i> carry</b>
        <ul>${s.doesNotCarry.map(i => `<li>${md(i)}</li>`).join('')}</ul></div>
    </div>
    <p><b>Where it comes from</b><br>${md(s.origin)}</p>
    <p class="muted">${meta.join(' · ')}</p>
    ${s.notes ? `<div class="banner info">${md(s.notes)}</div>` : ''}
  </div>`;
}

export async function render(container) {
  container.innerHTML = '<p class="muted">Loading source descriptions…</p>';
  if (!payload) {
    const url = new URL('../data/sources.json', import.meta.url);
    payload = await fetch(url.href).then(r => r.json());
  }
  const p = payload;
  const custom = Object.values(backbone.registered());

  container.innerHTML = '';
  container.appendChild(el(`<div>
    <h1>Data sources</h1>
    <p class="caption">Five sources go into the consolidated database. They are not
      interchangeable — two describe taxonomy, two describe regulation, and one
      supplies synonym typing the others cannot.</p>

    <h3>The two CITES sources are different things</h3>
    <p>This is the distinction that trips people up most often, so it is worth
      stating plainly. <b><code>cites_csv</code> and <code>cites_pdf</code> are not
      two formats of one dataset.</b> They answer different questions and neither
      substitutes for the other.</p>
    ${table(['', 'cites_csv — the listings', 'cites_pdf — the checklist'],
      p.citesDistinction.map(r => [`<b>${esc(r.question)}</b>`, md(r.citesCsv), md(r.citesPdf)]))}
    <p>The practical consequence: a name can be <b>accepted in <code>cites_csv</code>
      and a synonym everywhere else</b>, because the listings table records the name
      under which a taxon is regulated, not the name a botanist would use today.
      That is the single most common cause of a <code>status_conflict</code>, and it
      is a real regulatory fact rather than a data error — which is why such names
      are surfaced rather than silently resolved.</p>

    <h3>Every source in detail</h3>
    ${p.sources.map(sourceCard).join('')}

    <h3>Your own checklists</h3>
    ${custom.length
      ? `<ul>${custom.map(bb => `<li><b>${esc(bb.label)}</b> <code>${esc(bb.id)}</code>
          — ${backbone.nameCount(bb).toLocaleString()} names, compared alongside the
          five built-in sources.</li>`).join('')}</ul>`
      : `<div class="banner info">You can add your own backbone — an authority
          database such as WISIA, or any checklist CSV — from the
          <b>Your own checklists</b> page. It is then compared alongside these five
          everywhere in the app.</div>`}

    <h3>How <code>contest_class</code> is decided</h3>
    <p>When sources cannot be reconciled on a name, the name is held out of the
      consolidated table and written to <code>contested_names.csv</code> instead —
      one row per source, so you can see who said what. <code>contest_class</code>
      records <b>which comparison failed</b>.</p>
    ${p.contestClasses.map(c => `<div class="panel">
      <div>${chip(c.id, CLASS_CHIP[c.id] || 'neutral')} &nbsp; <b>${esc(c.headline)}</b>
        <span class="kind">${(p.contestClassCounts[c.id] || 0).toLocaleString()} binomials</span></div>
      <p>${md(c.definition)}</p>
      <p><b>Fields compared:</b> ${md(c.compared)}</p>
      <p class="muted">Example — ${md(c.example)}</p>
    </div>`).join('')}

    <h3>What is deliberately <i>not</i> compared</h3>
    ${p.notCompared.map(n => `<p><b>${esc(n.title)}.</b> ${md(n.body)}</p>`).join('')}

    <h3>Coming: CITES Standard Nomenclatures</h3>
    <p>Machine-readable editions of the <b>CITES Standard Nomenclatures</b>, current
      and historical, are the obvious next sources to add: they are the reference
      the Parties actually adopted, and historical editions would let a name be
      checked against the nomenclature in force when a permit was issued.</p>
    <p>The pipeline is already shaped for this. Adding a source means writing a
      cleaner that emits <code>Chigualen/data/clean/&lt;id&gt;.csv</code> in the
      frozen schema, appending one <code>Source(...)</code> entry to
      <code>scripts/_sources.py</code>, and adding its id to
      <code>PIPELINE_ORDER</code>. Nothing else changes: consolidation, the conflict
      classes, the species cards, this page and the export all read the registry.
      A historical edition would enter as its own source rather than replacing the
      current one, so an edition-to-edition disagreement surfaces as an ordinary
      <code>status_conflict</code>.</p>

    <h3>What is in this build</h3>
    <div class="stats">
      <div class="stat plain"><div class="n">${p.counts.species.toLocaleString()}</div>
        <div class="l">Accepted species</div></div>
      <div class="stat plain"><div class="n">${p.counts.synonymPairs.toLocaleString()}</div>
        <div class="l">Synonym pairs</div></div>
      <div class="stat plain"><div class="n">${p.counts.contested.toLocaleString()}</div>
        <div class="l">Contested binomials</div></div>
      <div class="stat plain"><div class="n">${p.counts.withYear.toLocaleString()}</div>
        <div class="l">With a description year</div></div>
    </div>
    ${table(['Source', 'Kind', 'Species touched', 'Licence'],
      p.sources.map(s => [
        `${chip(s.id, 'src-' + s.id)} ${esc(s.label)}`,
        esc(KIND_LABEL[s.kind] || s.kind),
        s.speciesTouched.toLocaleString(),
        esc(s.licence)]))}
  </div>`));
}
