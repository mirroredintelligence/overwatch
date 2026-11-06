import type { StatusCode } from '@/components/ui/StatusBadge';
import type { BoardEntry } from '@/lib/board/types';
import { agoText } from '@/lib/lead/format';

// The advisor's list of services by state (DEC-1343), opened from the counts on the advisor home. It is read from the
// board and is not a ranking: services are listed by name, never by status, so a stale "accepting" can never come
// first. A late or old figure is not shown as a number: the row says the capacity is unavailable.

/** The states the home counts and this list can filter by, in the board's order. */
export const BROWSE_STATUSES: readonly StatusCode[] = ['accepting', 'limited', 'over-capacity', 'not-accepting', 'not-updated'];

/** A figure older than this is not shown as the current capacity (the same two hours as the options). */
export const OLD_AFTER_MS = 2 * 60 * 60_000;

/** The statuses named in `?status=a,b`, in the board's order; anything else in the address is ignored. */
export function statusesFromQuery(value: string | string[] | undefined): StatusCode[] {
  const text = Array.isArray(value) ? (value[0] ?? '') : (value ?? '');
  const named = new Set(text.split(',').map((part) => part.trim()));
  return BROWSE_STATUSES.filter((status) => named.has(status));
}

export function figureUnavailable(entry: BoardEntry, now: number): boolean {
  if (entry.status === 'not-updated') return true;
  return entry.reportedAt !== null && now - Date.parse(entry.reportedAt) > OLD_AFTER_MS;
}

export type BrowseRow = {
  serviceId: string;
  name: string;
  category: string;
  status: StatusCode;
  /** The figure as text, or null when the capacity is unavailable (late, old or unknown). */
  figure: string | null;
  unitLabel: string;
  /** "Updated 12 min ago", or "No report yet". */
  updated: string;
};

function figureText(entry: BoardEntry): string | null {
  if (entry.status === 'over-capacity' && entry.overBy !== null) return `+${entry.overBy}`;
  return entry.effectiveAvailable === null ? null : String(entry.effectiveAvailable);
}

export function countsOf(entries: readonly BoardEntry[]): Record<StatusCode, number> {
  const counts: Record<StatusCode, number> = {
    accepting: 0,
    limited: 0,
    'not-accepting': 0,
    'over-capacity': 0,
    'not-updated': 0,
    'out-of-hours': 0,
    'last-known': 0,
  };
  for (const entry of entries) counts[entry.status] += 1;
  return counts;
}

/** The rows for the chosen states (all five when none is chosen), by name and then id: never by status. */
export function browseRows(entries: readonly BoardEntry[], selected: readonly StatusCode[], now: number): BrowseRow[] {
  const wanted = new Set<StatusCode>(selected.length === 0 ? BROWSE_STATUSES : selected);
  return entries
    .filter((entry) => wanted.has(entry.status))
    .map((entry) => ({
      serviceId: entry.serviceId,
      name: entry.name,
      category: entry.category,
      status: entry.status,
      figure: figureUnavailable(entry, now) ? null : figureText(entry),
      unitLabel: entry.unitLabel,
      updated: entry.reportedAt === null ? 'No report yet' : `Updated ${agoText(entry.reportedAt, now)}`,
    }))
    .sort((a, b) => a.name.localeCompare(b.name) || a.serviceId.localeCompare(b.serviceId));
}
