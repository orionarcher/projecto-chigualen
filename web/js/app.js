/** Shell and router. */
import * as data from './data.js';
import * as search from './search.js';
import * as ingest from './ingest.js';
import { esc } from './ui.js';

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
      <div class="stat" style="border-color:var(--line)">
        <div class="n">${idx.counts.species.toLocaleString()}</div><div class="l">Accepted species</div></div>
      <div class="stat" style="border-color:var(--line)">
        <div class="n">${idx.counts.synonymPairs.toLocaleString()}</div><div class="l">Synonym pairs</div></div>
      <div class="stat" style="border-color:var(--line)">
        <div class="n">${idx.counts.contested.toLocaleString()}</div><div class="l">Contested binomials</div></div>
    </div>
    <h3>Sources</h3>
    <ul>${idx.sources.map(s =>
      `<li><b>${esc(idx.sourceLabels[s])}</b> <code>${esc(s)}</code></li>`).join('')}</ul>
    <p class="muted">This is a static build of the Streamlit app. The pipeline that
      produces the data is unchanged and still runs offline.</p>`;
}

const PAGES = {
  search: (c) => search.render(c),
  ingest: (c) => ingest.render(c),
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
  } catch (err) {
    main.innerHTML = `<div class="banner error"><h4>Could not load the index</h4>
      <p>${esc(err.message)}</p>
      <p class="muted">If you opened this file directly, the browser blocks fetch on
      <code>file://</code>. Serve the folder instead:
      <code>python3 -m http.server -d web</code></p></div>`;
  }
})();
