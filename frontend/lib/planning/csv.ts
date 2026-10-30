// The planning export (W51): the flows and the declined rows as CSV, from the same data the page
// shows. A count under 10 is written as an empty field, so a small number never leaves the page.
// Fields are quoted when they hold a comma, a quote or a line break, and quotes are doubled.

import type { Planning } from './types';

const HEADER = 'Section,Best fit,State,Went to,Referrals';

function field(value: string | number | null): string {
  if (value === null) return '';
  const text = String(value);
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function toCsv(planning: Planning): string {
  const rows: string[] = [HEADER];
  for (const flow of planning.flows) {
    const count = flow.suppressed ? null : flow.count;
    rows.push([field('Flow'), field(flow.bestFit), field(flow.state), field(flow.wentTo), field(count)].join(','));
  }
  for (const row of planning.declinedDespite) {
    const count = row.suppressed ? null : row.count;
    rows.push([field('Declined'), field(row.service), field(''), field(''), field(count)].join(','));
  }
  return `${rows.join('\r\n')}\r\n`;
}
