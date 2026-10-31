import { describe, expect, it } from 'vitest';
import { BOARD_BODY, boardEntry } from '@/test/fixtures/network';
import { agesText, dayText, delayedOrganisations, goneOrganisations, networkToWallBoard, toBoardEntry } from './entries';
import { parseBoard } from './parse';
import type { NetworkBoard, NetworkBoardEntry } from './types';

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

// TEN-072: a network's board as the wall board reads it.
describe('networkToWallBoard', () => {
  const entry = (over: Partial<NetworkBoardEntry> = {}): NetworkBoardEntry => ({
    rowRef: 'lst-1',
    organisationName: 'Sample Area B',
    serviceName: 'Virtual ward frailty',
    category: 'hospital-at-home-or-virtual-ward',
    presentation: 'shown',
    status: 'limited',
    unitLabel: 'beds',
    effectiveAvailable: 1,
    overBy: null,
    used: 9,
    established: 10,
    reportedAt: '2026-10-23T13:08:00Z',
    staleWarning: false,
    wasDueAt: null,
    ...over,
  });
  const networkBoard = (entries: NetworkBoardEntry[]): NetworkBoard => ({
    entries,
    pressure: 'watch',
    allLimitedOrWorse: false,
    generatedAt: '2026-10-23T13:12:00Z',
    systemName: 'Sample capacity',
    pathwayName: 'Sample pathway',
    timeZone: 'Europe/London',
  });

  it('keeps the rows in the order the back end sent them, with the organisation under each name', () => {
    const wall = networkToWallBoard(networkBoard([entry({ rowRef: 'lst-9', organisationName: 'Zeta' }), entry({ rowRef: 'lst-2', organisationName: 'Alpha' })]), null);
    expect(wall.entries.map((item) => [item.serviceId, item.organisation])).toEqual([['lst-9', 'Zeta'], ['lst-2', 'Alpha']]);
    expect(wall.pressure).toBe('watch');
    expect(wall.generatedAt).toBe('2026-10-23T13:12:00Z');
    expect(wall.organisation).toBeNull();
  });

  it('marks the viewer’s own organisation’s rows', () => {
    const wall = networkToWallBoard(networkBoard([entry({ organisationName: 'Own Trust' }), entry({ rowRef: 'lst-2', organisationName: 'Other' })]), 'Own Trust');
    expect(wall.entries.map((item) => item.ownOrganisation)).toEqual([true, false]);
  });

  it('has no comment, no pending count and no next-due time on any row (a network does not share them)', () => {
    const [row] = networkToWallBoard(networkBoard([entry()]), null).entries;
    expect(row).toMatchObject({ comment: null, pending: 0, nextDueAt: null });
  });

  it('shows a paused listing as Not updated with no figure and says it is paused', () => {
    const [row] = networkToWallBoard(networkBoard([entry({ presentation: 'unavailable', status: null, unitLabel: null, effectiveAvailable: null, used: null })]), null).entries;
    expect(row).toMatchObject({ status: 'not-updated', effectiveAvailable: null, used: null, paused: true, unitLabel: 'Phone to confirm' });
  });
});


describe('agesText (WB11)', () => {
  it('says the range, or "and over" when there is no upper limit', () => {
    expect(agesText(18, 120)).toBe('18 to 120');
    expect(agesText(18, null)).toBe('18 and over');
  });
});
