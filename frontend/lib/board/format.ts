import type { BoardEntry } from './types';

// Text for the wall board. Pure functions of an instant and a clock, so the
// same board always reads the same. Times are shown in London local time
// (domain-rules 1.4, 1.5); the back end sends UTC.

type Instant = string | Date;

const MINUTE_MS = 60_000;
const LONDON = 'Europe/London';

function ms(instant: Instant): number {
  return typeof instant === 'string' ? Date.parse(instant) : instant.getTime();
}

/** "1 min", "45 min", "1 hr", "4 hrs 10 min", "3 hrs". Whole minutes. */
export function durationText(minutes: number): string {
  if (minutes < 1) return 'under 1 min';
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  const hoursText = hours === 0 ? '' : `${hours} ${hours === 1 ? 'hr' : 'hrs'}`;
  const restText = rest === 0 ? '' : `${rest} min`;
  return [hoursText, restText].filter(Boolean).join(' ');
}

/** Domain-rules 1.5: "just now", "N min ago", "1 hr 5 min ago", "3 hrs ago". */
export function dataAgeText(reportedAt: Instant, now: Instant): string {
  const minutes = Math.floor((ms(now) - ms(reportedAt)) / MINUTE_MS);
  // Under a minute, and a figure dated after the clock, both read "just now".
  if (minutes < 1) return 'just now';
  return `${durationText(minutes)} ago`;
}

const timeFormat = new Intl.DateTimeFormat('en-GB', {
  timeZone: LONDON,
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});

/** "HH:MM" in London local time. */
export function londonTime(instant: Instant): string {
  return timeFormat.format(ms(instant));
}

const dateParts = new Intl.DateTimeFormat('en-GB', {
  timeZone: LONDON,
  weekday: 'long',
  day: 'numeric',
  month: 'long',
});

function part(parts: Intl.DateTimeFormatPart[], type: Intl.DateTimeFormatPartTypes): string {
  return parts.find((p) => p.type === type)?.value ?? '';
}

/** "Friday 23 October" in London local time. */
export function londonDate(instant: Instant): string {
  const parts = dateParts.formatToParts(ms(instant));
  return `${part(parts, 'weekday')} ${part(parts, 'day')} ${part(parts, 'month')}`;
}

const dayKey = new Intl.DateTimeFormat('en-CA', { timeZone: LONDON, year: 'numeric', month: '2-digit', day: '2-digit' });
const weekdayName = new Intl.DateTimeFormat('en-GB', { timeZone: LONDON, weekday: 'long' });

/** Whole London calendar days from `now` to `instant` (0 same day, 1 next day). */
function daysBetween(instant: Instant, now: Instant): number {
  const toDay = (value: Instant) => Date.parse(`${dayKey.format(ms(value))}T00:00:00Z`);
  return Math.round((toDay(instant) - toDay(now)) / 86_400_000);
}

/** "next due 14:30", "next due 09:00 tomorrow", or "next due 09:00 Monday". */
export function nextDueText(nextDueAt: Instant, now: Instant): string {
  const time = londonTime(nextDueAt);
  const days = daysBetween(nextDueAt, now);
  if (days <= 0) return `next due ${time}`;
  if (days === 1) return `next due ${time} tomorrow`;
  return `next due ${time} ${weekdayName.format(ms(nextDueAt))}`;
}

/**
 * The age line under a tile. A service that is not updated says for how long and
 * when the figure was due; every other status says how old the figure is and when
 * the next one is due.
 */
export function ageLineText(entry: BoardEntry, now: Instant): string {
  const wasDue = entry.wasDueAt === null ? null : `was due ${londonTime(entry.wasDueAt)}`;
  if (entry.status === 'not-updated') {
    const since =
      entry.reportedAt === null
        ? 'No figure reported yet'
        : `Not updated for ${durationText(Math.max(0, Math.floor((ms(now) - ms(entry.reportedAt)) / MINUTE_MS)))}`;
    return [since, wasDue].filter(Boolean).join(' · ');
  }
  if (entry.reportedAt === null) return 'No figure reported yet';
  const updated = `Updated ${dataAgeText(entry.reportedAt, now)}`;
  return entry.nextDueAt === null ? updated : `${updated} · ${nextDueText(entry.nextDueAt, now)}`;
}

const CATEGORY_LABELS: Record<string, string> = {
  'urgent-community-response': 'Urgent community response',
  'same-day-emergency-care': 'Same day emergency care',
  'inpatient-beds': 'Inpatient beds',
  'hospital-at-home-or-virtual-ward': 'Virtual beds',
  reablement: 'Care packages',
  'urgent-treatment': 'Urgent treatment',
  'mental-health-crisis': 'Mental health crisis',
  other: 'Other',
};

/** The label for a service category code. An unknown code becomes plain words, never the raw code. */
export function categoryLabel(category: string): string {
  const known = CATEGORY_LABELS[category];
  if (known !== undefined) return known;
  const words = category.replace(/-/g, ' ').trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}
