import { describe, expect, it } from 'vitest';
import type { BoardEntry } from '@/lib/board/types';
import { browseRows, countsOf, figureUnavailable, OLD_AFTER_MS, statusesFromQuery } from './servicesBrowse';

// The services by state (DEC-1343): by name, never by status, and a late or old figure is never a number.

const NOW = Date.parse('2026-11-06T14:00:00Z');

function entry(over: Partial<BoardEntry>): BoardEntry {
  return {
    serviceId: 'svc',
    name: 'Service',
    category: 'urgent-community-response',
    status: 'accepting',
    effectiveAvailable: 4,
    overBy: null,
    used: 6,
    established: 10,
    pending: 0,
    unitLabel: 'beds free',
    comment: null,
    reportedAt: '2026-11-06T13:30:00Z',
    nextDueAt: '2026-11-06T15:30:00Z',
    wasDueAt: null,
    ...over,
  };
}

describe('statusesFromQuery', () => {
  it('reads the statuses named, in the board order, and ignores anything else', () => {
    expect(statusesFromQuery('limited,accepting,bogus')).toEqual(['accepting', 'limited']);
    expect(statusesFromQuery(['not-updated'])).toEqual(['not-updated']);
    expect(statusesFromQuery(undefined)).toEqual([]);
    expect(statusesFromQuery('')).toEqual([]);
  });
});

describe('figureUnavailable', () => {
  it('is true for a late report and for a figure older than two hours, and false otherwise', () => {
    expect(figureUnavailable(entry({ status: 'not-updated' }), NOW)).toBe(true);
    expect(figureUnavailable(entry({ reportedAt: new Date(NOW - OLD_AFTER_MS - 1000).toISOString() }), NOW)).toBe(true);
    expect(figureUnavailable(entry({ reportedAt: new Date(NOW - OLD_AFTER_MS).toISOString() }), NOW)).toBe(false);
    expect(figureUnavailable(entry({}), NOW)).toBe(false);
  });
});

describe('browseRows', () => {
  const entries = [
    entry({ serviceId: 'c', name: 'Charlie', status: 'limited' }),
    entry({ serviceId: 'a', name: 'Alpha', status: 'not-updated', effectiveAvailable: null }),
    entry({ serviceId: 'b', name: 'Bravo', status: 'accepting' }),
    entry({ serviceId: 'o', name: 'Over', status: 'over-capacity', overBy: 2, effectiveAvailable: 0 }),
    entry({ serviceId: 'h', name: 'Hours', status: 'out-of-hours' }),
  ];

  it('lists by name, not by status, so a stale accepting service is never first', () => {
    expect(browseRows(entries, [], NOW).map((row) => row.name)).toEqual(['Alpha', 'Bravo', 'Charlie', 'Over']);
  });

  it('filters to the chosen states and keeps the five counted states when none is chosen', () => {
    expect(browseRows(entries, ['limited', 'accepting'], NOW).map((row) => row.name)).toEqual(['Bravo', 'Charlie']);
    expect(browseRows(entries, [], NOW).map((row) => row.status)).not.toContain('out-of-hours');
  });

  it('shows no number for a late figure, and the surge as +n', () => {
    const rows = browseRows(entries, [], NOW);
    expect(rows.find((row) => row.name === 'Alpha')?.figure).toBeNull();
    expect(rows.find((row) => row.name === 'Over')?.figure).toBe('+2');
    expect(rows.find((row) => row.name === 'Bravo')?.figure).toBe('4');
  });

  it('says how long ago it was updated, or that there is no report', () => {
    const rows = browseRows([entry({ name: 'A', serviceId: 'a' }), entry({ name: 'B', serviceId: 'b', reportedAt: null })], [], NOW);
    expect(rows[0].updated).toBe('Updated 30 min ago');
    expect(rows[1].updated).toBe('No report yet');
  });
});

describe('countsOf', () => {
  it('counts each status', () => {
    const counts = countsOf([entry({}), entry({}), entry({ status: 'limited' })]);
    expect(counts.accepting).toBe(2);
    expect(counts.limited).toBe(1);
    expect(counts['not-updated']).toBe(0);
  });
});
