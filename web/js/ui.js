/** Small rendering helpers shared by the pages. */
import { index, STATUS } from './data.js';

export const el = (html) => { const t = document.createElement('template');
  t.innerHTML = html.trim(); return t.content.firstElementChild; };

export const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export function chip(label, colour) {
  return `<span class="chip" style="color:${colour};background:${colour}22;border-color:${colour}55">${esc(label)}</span>`;
}

export const sourceColour = (s) => index()?.sourceColours?.[s] || '#5a6472';
export const sourceLabel = (s) => index()?.sourceLabels?.[s] || s;

export const sourceChips = (value) =>
  (value || '').replace(/\|/g, ',').split(',').map(s => s.trim()).filter(Boolean)
    .map(s => chip(s, sourceColour(s))).join('');

export const STATUS_STYLE = {
  [STATUS.ACCEPTED]:  ['accepted',     'var(--accepted)'],
  [STATUS.SYNONYM]:   ['synonym',      'var(--synonym)'],
  [STATUS.CONTESTED]: ['contested',    'var(--contested)'],
  [STATUS.ABSENT]:    ['not in source','var(--absent)'],
};

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
    const [label, colour] = STATUS_STYLE[v.status] || [v.status, 'var(--dim)'];
    return [
      `<b>${esc(sourceLabel(s))}</b><br><span class="muted">${esc(s)}</span>`,
      `<span style="color:${colour}">${esc(label)}</span>`,
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
