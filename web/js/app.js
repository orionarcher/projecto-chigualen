/** Shell and router. */
import * as data from './data.js';
import * as search from './search.js';
import * as ingest from './ingest.js';
import * as backbone from './backbone.js';
import * as sources from './sources.js';
import { esc } from './dom.js';

const main = document.getElementById('main');
const bar = document.getElementById('boot-bar');
const note = document.getElementById('boot-note');

function about(container) {
  const idx = data.index();
  container.innerHTML = `
    <h1>About Chigualen</h1>
    <p class="lede">One place to find out what an orchid name means: whether it is
      current, what it is a synonym of, whether CITES regulates it, and — where the
      authorities disagree — exactly who says what.</p>

    <div class="stats">
      <div class="stat plain"><div class="n">${idx.counts.species.toLocaleString()}</div>
        <div class="l">Accepted species</div></div>
      <div class="stat plain"><div class="n">${idx.counts.synonymPairs.toLocaleString()}</div>
        <div class="l">Synonym pairs</div></div>
      <div class="stat plain"><div class="n">${idx.counts.contested.toLocaleString()}</div>
        <div class="l">Contested names</div></div>
    </div>

    <div class="section">What you can do here</div>
    <ul>
      <li><b>Look up a name.</b> Search by the current name or any synonym.
        Suggestions appear as you type — including on the species epithet alone,
        which matters when the genus has changed since the name was written, and
        through spelling mistakes.</li>
      <li><b>Check a list of names.</b> Upload a spreadsheet of names and get back
        one row per name saying how each resolves, what every source says about it
        individually, and the reason behind any disagreement.</li>
      <li><b>Compare against your own list.</b> Load your authority's own checklist
        and it is compared alongside the five reference sources everywhere, with
        disagreements called out.</li>
    </ul>

    <div class="section">Where the answers come from</div>
    <p>Five sources: two global taxonomic checklists, the CITES listings, the CITES
      Appendix II Orchid Checklist, and a curated synonym list. Where they agree,
      the name is settled. Where they do not, it is held back and shown to you with
      the disagreement spelled out rather than resolved silently behind your back.
      See <b>Data sources</b> for what each one is authoritative for.</p>

    <div class="section">Your data</div>
    <p>Nothing you type or upload is transmitted anywhere. The database is
      downloaded to your browser once, and every search, comparison and export
      after that happens on your own machine — which is why a checklist you load
      here never leaves it.</p>`;
}

const PAGES = {
  search: (c) => search.render(c),
  ingest: (c) => ingest.render(c),
  checklists: (c) => backbone.render(c),
  sources: (c) => sources.render(c),
  about,
};

function go(page) {
  document.querySelectorAll('#nav button').forEach(b =>
    b.setAttribute('aria-current', b.dataset.page === page ? 'page' : 'false'));
  location.hash = page;
  (PAGES[page] || PAGES.search)(main);
}

document.getElementById('nav').addEventListener('click', (e) => {
  const b = e.target.closest('button');
  if (b) go(b.dataset.page);
});

(async () => {
  try {
    const t0 = performance.now();
    await data.load((frac, bytes) => {
      if (frac !== null) bar.style.width = `${Math.round(frac * 100)}%`;
      note.textContent = `${(bytes / 1e6).toFixed(1)} MB`;
    });
    note.textContent = `ready in ${Math.round(performance.now() - t0)} ms`;
    go((location.hash || '#search').slice(1));
    // Warm the search structures once the page is interactive.
    (window.requestIdleCallback || ((f) => setTimeout(f, 200)))(() => data.warmSearch());
  } catch (err) {
    main.innerHTML = `<div class="banner error"><h4>Could not load the index</h4>
      <p>${esc(err.message)}</p>
      <p class="muted">If you opened this file directly, the browser blocks fetch on
      <code>file://</code>. Serve the folder instead:
      <code>python3 -m http.server -d web</code></p></div>`;
  }
})();
