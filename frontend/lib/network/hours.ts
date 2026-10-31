import type { OpeningHour } from './types';

// A service's opening hours in words, from the windows the organisation shared (TEN-071). Days are 0
// (Monday) to 6 (Sunday); times are the service's own, as shared. Nothing is invented: no window is "Opening
// hours not shared".

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] as const;
const RUN = 3;

function daysText(days: readonly number[]): string {
  const sorted = [...new Set(days)].sort((a, b) => a - b);
  if (sorted.length === 7) return 'Every day';
  const parts: string[] = [];
  let at = 0;
  while (at < sorted.length) {
    let end = at;
    while (end + 1 < sorted.length && sorted[end + 1] === (sorted[end] as number) + 1) end += 1;
    const first = DAYS[sorted[at] as number] ?? '';
    if (end - at + 1 >= RUN) parts.push(`${first} to ${DAYS[sorted[end] as number] ?? ''}`);
    else for (let i = at; i <= end; i += 1) parts.push(DAYS[sorted[i] as number] ?? '');
    at = end + 1;
  }
  return parts.join(', ');
}

function windowText(hour: OpeningHour): string {
  const days = daysText(hour.days);
  if (hour.allDay) return `${days}, all day`;
  return `${days} ${hour.start ?? ''} to ${hour.end ?? ''}`.trim();
}

export function hoursText(hours: readonly OpeningHour[]): string {
  if (hours.length === 0) return 'Opening hours not shared';
  return [...hours]
    .sort((a, b) => a.position - b.position)
    .map(windowText)
    .join('; ');
}
