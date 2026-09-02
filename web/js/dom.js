/** Rendering helpers with no dependencies of their own.
 *
 *  Split out of ui.js so the module graph stays a DAG: backbone.js and
 *  sources.js need these, and ui.js needs backbone.js, which would otherwise be
 *  a cycle. ES modules tolerate cycles, but only until someone touches an
 *  imported binding during module evaluation rather than inside a function.
 *
 *  Colours come from classes, never a style attribute — see the note in
 *  css/style.css about the Content-Security-Policy this site is served with.
 */

export const el = (html) => {
  const t = document.createElement('template');
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
};

export const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export function chip(label, cls = 'neutral') {
  return `<span class="chip ${cls}">${esc(label)}</span>`;
}

/** Source ids as coloured chips, labelled with the source's name rather than its
 *  internal id. Accepts the pipe-joined form used in the long table and the
 *  comma-joined form used in the wide one.
 *
 *  `names` maps id → short name; callers pass index().sourceShort. Without it the
 *  id is shown, which is the right fallback for a checklist the reader named. */
export const sourceChips = (value, names = {}) =>
  (value || '').replace(/\|/g, ',').split(',').map(s => s.trim()).filter(Boolean)
    .map(s => chip(names[s] || s, `src-${s}`)).join('');

/** Class for a synonym type as it appears in synonyms_detailed. */
export const typeClass = (t) => ({
  Homotypic: 'ty-homotypic', Heterotypic: 'ty-heterotypic',
  'Orthographic variant': 'ty-orthographic', Nomenclatural: 'ty-nomenclatural',
  Mixed: 'ty-mixed',
}[t] || 'ty-unknown');

export const citesClass = (appendix) =>
  ({ I: 'cites-i', II: 'cites-ii', III: 'cites-iii' }[appendix] || 'neutral');

export function table(headers, rows) {
  if (!rows.length) return '';
  return `<div class="scroll-x"><table><thead><tr>${
    headers.map(h => `<th>${esc(h)}</th>`).join('')
  }</tr></thead><tbody>${
    rows.map(r => `<tr>${r.map(c => `<td>${c}</td>`).join('')}</tr>`).join('')
  }</tbody></table></div>`;
}
