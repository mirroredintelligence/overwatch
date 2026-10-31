import { describe, expect, it } from 'vitest';
import { BOARD_BODY, boardEntry } from '@/test/fixtures/network';
import { dayText, delayedOrganisations, goneOrganisations, toBoardEntry } from './entries';
import { parseBoard } from './parse';

// TEN-070: small pure rules of the network board page.

const board = parseBoard(BOARD_BODY, 'backend');
const entries = (list: unknown[]) => parseBoard({ ...BOARD_BODY, entries: list }, 'backend').entries;

describe('toBoardEntry (a network row as the wall tile reads it)', () => {
  it('keeps the figures and drops what a network does not share', () => {
    expect(toBoardEntry(board.entries[0]!)).toEqual({
      serviceId: 'lst-0001',
      name: 'UCR West',
      category: 'urgent-community-response',
      status: 'accepting',
      effectiveAvailable: 4,
      overBy: null,
      used: 2,
      established: 6,
      pending: 0,
      unitLabel: 'beds',
      comment: null,
      reportedAt: '2026-10-23T13:08:00+00:00',
      nextDueAt: null,
      wasDueAt: null,
    });
  });

  it('reads a paused listing as Not updated with no figure, never as a status of its own', () => {
    expect(toBoardEntry(board.entries[3]!)).toMatchObject({ status: 'not-updated', established: 0, unitLabel: 'Phone to confirm', used: null });
  });
});

describe('delayedOrganisations', () => {
  it('is an organisation whose every shown service is Not updated', () => {
    const list = entries([
      boardEntry({ row_ref: 'a', organisation_name: 'B', status: 'not-updated', stale_warning: true }),
      boardEntry({ row_ref: 'b', organisation_name: 'B', status: 'not-updated', stale_warning: true }),
      boardEntry({ row_ref: 'c', organisation_name: 'A' }),
      boardEntry({ row_ref: 'd', organisation_name: 'C', status: 'not-updated', stale_warning: true }),
      boardEntry({ row_ref: 'e', organisation_name: 'C' }),
    ]);
    expect(delayedOrganisations(list)).toEqual(['B']);
  });

  it('does not count a paused listing, or an out-of-hours service, as a delay', () => {
    const list = entries([
      boardEntry({ row_ref: 'a', organisation_name: 'B', presentation: 'unavailable', status: null, unit_label: null, effective_available: null, used: null, established: null, reported_at: null }),
      boardEntry({ row_ref: 'b', organisation_name: 'C', status: 'out-of-hours' }),
    ]);
    expect(delayedOrganisations(list)).toEqual([]);
  });

  it('is in alphabetical order', () => {
    const list = entries([
      boardEntry({ row_ref: 'a', organisation_name: 'Z', status: 'not-updated', stale_warning: true }),
      boardEntry({ row_ref: 'b', organisation_name: 'B', status: 'not-updated', stale_warning: true }),
    ]);
    expect(delayedOrganisations(list)).toEqual(['B', 'Z']);
  });
});

describe('goneOrganisations', () => {
  it('is an organisation that was on the board before and is not now', () => {
    const before = entries([boardEntry({ organisation_name: 'A' }), boardEntry({ row_ref: 'b', organisation_name: 'B' })]);
    const now = entries([boardEntry({ organisation_name: 'A' })]);
    expect(goneOrganisations(before, now)).toEqual(['B']);
  });

  it('is none when no organisation left, and none for one that only has fewer services', () => {
    const before = entries([boardEntry({ organisation_name: 'A' }), boardEntry({ row_ref: 'b', organisation_name: 'A', service_name: 'S2' })]);
    const now = entries([boardEntry({ organisation_name: 'A' })]);
    expect(goneOrganisations(before, now)).toEqual([]);
  });
});

describe('dayText', () => {
  it('writes a day in London time, as "1 October 2026"', () => {
    expect(dayText('2026-10-01T09:00:00+00:00')).toBe('1 October 2026');
    expect(dayText('2026-12-31T23:30:00+00:00')).toBe('31 December 2026');
    expect(dayText('2026-06-30T23:30:00+00:00')).toBe('1 July 2026');
  });
});
