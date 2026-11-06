import { clockTime, overdueText } from '@/lib/lead/format';
import type { OptionView } from './options';

// What a service promised and what it did (DEC-1343): when it last reported, how often it reports, when the next
// report is due, and whether it is late. A late or old figure is never shown as the current capacity; the card says
// so, and the last figure is shown small as "Last reported". Pure.

const CADENCE_WORDS: Record<string, string> = {
  'every-2-hrs': 'Every 2 hrs',
  'twice-a-day': 'Twice a day',
  'once-a-day': 'Once a day',
};

const NOT_KNOWN = 'Not known';

export function cadenceWords(code: string | null): string {
  return code === null ? NOT_KNOWN : (CADENCE_WORDS[code] ?? NOT_KNOWN);
}

export type ReportingStrip = {
  lastUpdate: string;
  frequency: string;
  nextDue: string;
  /** "On schedule" or "Overdue": words, never colour alone. */
  schedule: string;
  overdue: boolean;
};

/** The strip for a service, or null when nothing about its reporting is known (a network service's card has none). */
export function reportingStrip(option: OptionView): ReportingStrip | null {
  if (option.reportedAt === null && option.nextDueAt === null && option.cadence === null) return null;
  return {
    lastUpdate: option.reportedAt === null ? 'No report yet' : clockTime(option.reportedAt),
    frequency: cadenceWords(option.cadence),
    nextDue: option.nextDueAt === null ? NOT_KNOWN : clockTime(option.nextDueAt),
    schedule: option.overdue ? 'Overdue' : 'On schedule',
    overdue: option.overdue,
  };
}

/** The small line under "Current capacity unavailable": the last figure and how old it is. */
export function lastReportedLine(option: OptionView): string {
  const age =
    option.dataAgeSeconds === null ? null : `${overdueText(Math.floor(option.dataAgeSeconds / 60))} ago`;
  if (option.lastFigure === null) return age === null ? 'No figure reported' : `No figure. Last report ${age}`;
  const figure = `${option.lastFigure} ${option.unitLabel ?? ''}`.trim();
  return age === null ? `Last reported: ${figure}` : `Last reported: ${figure} · ${age}`;
}
