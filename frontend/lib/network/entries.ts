import type { BoardEntry } from '@/lib/board/types';
import type { NetworkBoardEntry } from './types';

// Small pure rules of the network board page (TEN-070).

const LONDON = 'Europe/London';
const dayFormat = new Intl.DateTimeFormat('en-GB', { timeZone: LONDON, day: 'numeric', month: 'long', year: 'numeric' });

/** A day in London time, written "1 October 2026". */
export function dayText(instant: string): string {
  return dayFormat.format(Date.parse(instant));
}

/**
 * A network row as the wall tile reads it: the figures, and none of what a network does not share (no
 * pending count, no comment, no next-due time). A paused listing has no figure and no status: it reads
 * Not updated with nothing to rely on, never a status word of its own (docs/design/network-ui.md section 13).
 */
export function toBoardEntry(entry: NetworkBoardEntry): BoardEntry {
  const paused = entry.presentation === 'unavailable' || entry.status === null;
  return {
    serviceId: entry.rowRef,
    name: entry.serviceName,
    category: entry.category,
    status: paused ? 'not-updated' : entry.status ?? 'not-updated',
    effectiveAvailable: paused ? null : entry.effectiveAvailable,
    overBy: paused ? null : entry.overBy,
    used: paused ? null : entry.used,
    established: entry.established ?? 0,
    pending: 0,
    unitLabel: entry.unitLabel ?? 'Phone to confirm',
    comment: null,
    reportedAt: paused ? null : entry.reportedAt,
    nextDueAt: null,
    wasDueAt: paused ? null : entry.wasDueAt,
  };
}

/** The organisations whose every shown service is Not updated: their updates are delayed. Alphabetical. */
export function delayedOrganisations(entries: readonly NetworkBoardEntry[]): string[] {
  const shown = entries.filter((entry) => entry.presentation === 'shown');
  const names = [...new Set(shown.map((entry) => entry.organisationName))];
  return names
    .filter((name) => shown.filter((entry) => entry.organisationName === name).every((entry) => entry.status === 'not-updated'))
    .sort((a, b) => a.localeCompare(b, 'en-GB'));
}

/** The organisations on the board before that are not on it now: they stopped sharing. Alphabetical. */
export function goneOrganisations(before: readonly NetworkBoardEntry[], now: readonly NetworkBoardEntry[]): string[] {
  const present = new Set(now.map((entry) => entry.organisationName));
  return [...new Set(before.map((entry) => entry.organisationName))].filter((name) => !present.has(name)).sort((a, b) => a.localeCompare(b, 'en-GB'));
}
