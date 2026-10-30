import { londonTime } from '@/lib/board/format';

// The reporter screens show the back end's UTC instants as the tenant's clock time (domain-rules 1.4):
// London time, "HH:MM". Anything that is not an instant shows as nothing, never as "Invalid Date".

const INSTANT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;

export function clock(instant: string | null | undefined): string {
  if (typeof instant !== 'string' || !INSTANT.test(instant) || Number.isNaN(Date.parse(instant))) return '';
  return londonTime(instant);
}

/** "In 30 days", "In 1 day", "Now". */
export function inDays(days: number): string {
  if (days <= 0) return 'Now';
  return `In ${days} ${days === 1 ? 'day' : 'days'}`;
}
