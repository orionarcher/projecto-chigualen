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
    <p>A consolidated orchid-species database built from five sources, served as a
      static site. <b>There is no backend.</b> The name index is downloaded once and
      every lookup, diff and export runs in this browser tab — nothing you type or
      upload is transmitted anywhere.</p>
    <div class="stats">
      <div class="stat plain">
        <div class="n">${idx.counts.species.toLocaleString()}</div><div class="l">Accepted species</div></div>
      <div class="stat plain">
        <div class="n">${idx.counts.synonymPairs.toLocaleString()}</div><div class="l">Synonym pairs</div></div>
      <div class="stat plain">
        <div class="n">${idx.counts.contested.toLocaleString()}</div><div class="l">Contested binomials</div></div>
    </div>
    <h3>The pages</h3>
    <ul>
      <li><b>Search</b> — find a species by its accepted name or any known synonym.
        Suggestions appear as you type, including on the epithet alone and through
        typos. Every result shows what each source says on its own.</li>
      <li><b>Ingest authority CSV</b> — diff an external list against the database.
        The export carries a status and accepted name <i>per source</i>, plus the
        reason behind any contested verdict and the description year.</li>
      <li><b>Your own checklists</b> — load an authority's internal backbone and it
        is compared alongside the five built-in sources everywhere in the app.</li>
      <li><b>Data sources</b> — what each source is, where it comes from, and the
        exact rules behind <code>contest_class</code>.</li>
    </ul>
    <p class="muted">This is a static build of the Streamlit app in
      <code>app/</code>. The pipeline that produces the data is unchanged and still
      runs offline.</p>`;
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
