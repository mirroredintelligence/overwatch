import type { AuditReplay } from './audit';

// The replay as CSV for review (W47). The same fields as the screen, in one table: the services shown, then
// the timeline. A field with a comma, a quote or a line break is quoted, with its quotes doubled. A field
// that starts with a formula character gets an apostrophe, so a spreadsheet does not run it. Nothing here
// holds a postcode: the replay has none.

const HEADER = ['Type', 'Time', 'Service', 'Status', 'Figure', 'Data age', 'Criteria version', 'Event'];
const FORMULA = /^[=+\-@\t\r]/;

function field(value: string | number | null): string {
  let text = value === null ? '' : String(value);
  if (FORMULA.test(text)) text = `'${text}`;
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function toCsv(replay: AuditReplay): string {
  const versionOf = (name: string): number | null =>
    replay.criteriaVersions.find((c) => c.serviceName === name)?.version ?? null;
  const rows: (string | number | null)[][] = [HEADER];
  for (const shown of replay.shown) {
    rows.push(['shown', replay.decisionAt, shown.serviceName, shown.status, shown.value, shown.age, versionOf(shown.serviceName), '']);
  }
  for (const item of replay.timeline) {
    rows.push(['timeline', item.at, '', '', '', '', '', item.label]);
  }
  return rows.map((row) => row.map(field).join(',')).join('\r\n') + '\r\n';
}
