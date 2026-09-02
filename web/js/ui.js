/** Small rendering helpers shared by the pages. */
import { index, STATUS } from './data.js';

export const el = (html) => { const t = document.createElement('template');
  t.innerHTML = html.trim(); return t.content.firstElementChild; };

export const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/** Colours come from classes, never a style attribute — see the note in
 *  css/style.css about the Content-Security-Policy this site is served with. */
export function chip(label, cls = 'neutral') {
  return `<span class="chip ${cls}">${esc(label)}</span>`;
}

export const sourceLabel = (s) => index()?.sourceLabels?.[s] || s;

export const sourceChips = (value) =>
  (value || '').replace(/\|/g, ',').split(',').map(s => s.trim()).filter(Boolean)
    .map(s => chip(s, `src-${s}`)).join('');

export const STATUS_LABEL = {
  [STATUS.ACCEPTED]:  'accepted',
  [STATUS.SYNONYM]:   'synonym',
  [STATUS.CONTESTED]: 'contested',
  [STATUS.ABSENT]:    'not in source',
};

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

/** Per-source panel — the same resolution the export writes, as in app/search.py. */
export function perSourcePanel(res) {
  const rows = index().sources.map(s => {
    const v = res.perSource[s];
    const label = STATUS_LABEL[v.status] || v.status;
    return [
      `<b>${esc(sourceLabel(s))}</b><br><span class="muted">${esc(s)}</span>`,
      `<span class="st-${esc(v.status)}">${esc(label)}</span>`,
      `<span class="sci">${esc(v.acceptedName)}</span>`,
      `<span class="muted">${esc(v.detail)}</span>`,
    ];
  });
  return `<h3>What each source says</h3>
    <p class="caption">Resolved for <span class="sci">${esc(res.binomial)}</span>.
      <code>not in source</code> means that source has no record of this binomial —
      not that it rejects the name.</p>
    ${table(['Source', 'Says', 'Name it treats as current', 'Detail'], rows)}`;
}

export function downloadCsv(filename, rows) {
  if (!rows.length) return;
  const cols = Object.keys(rows[0]);
  const cell = (v) => {
    const s = v === null || v === undefined ? '' : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const csv = [cols.join(','), ...rows.map(r => cols.map(c => cell(r[c])).join(','))].join('\n');
  // A Blob URL keeps a multi-megabyte export off the address bar.
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const a = Object.assign(document.createElement('a'), { href: url, download: filename });
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
