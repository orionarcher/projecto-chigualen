/** Rendering that needs to know about the data or the loaded checklists.
 *  Dependency-free helpers live in dom.js. */

import { index, STATUS } from './data.js';
import * as backbone from './backbone.js';
import { esc, table } from './dom.js';

export * from './dom.js';

export const sourceLabel = (s) => index()?.sourceLabels?.[s] || s;
export const sourceShort = (s) => index()?.sourceShort?.[s] || s;
export const shortNames = () => index()?.sourceShort || {};

export const STATUS_LABEL = {
  [STATUS.ACCEPTED]:  'accepted',
  [STATUS.SYNONYM]:   'synonym',
  [STATUS.CONTESTED]: 'contested',
  [STATUS.ABSENT]:    'not in source',
};

/** One row per source: what does that source alone say about this name?
 *
 *  The same resolution the batch export writes into its `<source>_status` /
 *  `<source>_accepted_name` columns, so a single lookup and a bulk CSV can never
 *  tell different stories. Loaded checklists appear alongside the built-in
 *  sources, which is the whole point of loading one.
 */
export function perSourcePanel(res) {
  const row = (name, v) => [
    `<b>${name}</b>`,
    `<span class="st-${esc(v.status)}">${esc(STATUS_LABEL[v.status] || v.status)}</span>`,
    `<span class="sci">${esc(v.acceptedName)}</span>`,
    `<span class="muted">${esc(v.detail)}</span>`,
  ];

  const rows = index().sources.map(s => row(esc(sourceLabel(s)), res.perSource[s]));

  const mine = backbone.verdictsFor(res.binomial);
  const registered = backbone.registered();
  for (const [id, v] of Object.entries(mine)) {
    rows.push(row(`${esc(registered[id].label)} <span class="kind">yours</span>`, v));
  }

  return `<h3>What each source says</h3>
    <p class="caption">Resolved for <span class="sci">${esc(res.binomial)}</span>.
      &ldquo;Not in source&rdquo; means that source has no record of this name — not
      that it rejects it.</p>
    ${table(['Source', 'Says', 'Name it treats as current', 'Notes'], rows)}
    ${disagreementNote(res, mine, registered)}`;
}

/** Call out where a loaded checklist parts company with the consolidated
 *  result — the reason an authority loads one at all. */
function disagreementNote(res, mine, registered) {
  const differs = Object.entries(mine)
    .filter(([, v]) => v.status !== STATUS.ABSENT
                    && (v.acceptedName || '') !== (res.acceptedName || ''))
    .map(([id, v]) => `<b>${esc(registered[id].label)}</b> says `
      + esc(STATUS_LABEL[v.status] || v.status)
      + (v.acceptedName ? ` (<span class="sci">${esc(v.acceptedName)}</span>)` : ''));

  if (differs.length) {
    return `<div class="banner warn">Your checklist differs from the consolidated
      result: ${differs.join('; ')}.</div>`;
  }
  if (!Object.keys(registered).length) {
    return `<p class="muted">Load your own checklist on the <b>Your own checklists</b>
      page to see it compared here.</p>`;
  }
  return '';
}
