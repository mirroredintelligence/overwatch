import { describe, expect, it } from 'vitest';
import type { Board, BoardEntry } from '@/lib/board/types';
import { attentionLine, limitedOrWorse, needsAttention, pressureChip } from './homeSummary';

const base: BoardEntry = {
  serviceId: 's', name: 'S', category: 'urgent-community-response', status: 'accepting',
  effectiveAvailable: 4, overBy: null, used: 4, established: 8, pending: 0, unitLabel: 'referrals',
  comment: null, reportedAt: '2026-10-23T13:03:00Z', nextDueAt: null, wasDueAt: null,
};
const at = (status: BoardEntry['status'], id: string, extra: Partial<BoardEntry> = {}): BoardEntry =>
  ({ ...base, serviceId: id, name: id, status, ...extra });

const board = (entries: BoardEntry[], pressure = 'normal'): Board => ({
  entries, pressure, allLimitedOrWorse: false, generatedAt: '2026-10-23T13:12:00Z', organisation: 'Dorset',
});

describe('needsAttention', () => {
  it('lists over-capacity, not-accepting and not-updated services, and not limited or out-of-hours ones', () => {
    const result = needsAttention(board([
      at('over-capacity', 'a', { overBy: 4 }),
      at('not-accepting', 'b'),
      at('not-updated', 'c'),
      at('limited', 'd'),
      at('out-of-hours', 'e'),
      at('accepting', 'f'),
    ]));
    expect(result.map((e) => e.serviceId)).toEqual(['a', 'b', 'c']);
  });
});

describe('limitedOrWorse', () => {
  it('counts limited, not-accepting and over-capacity services against the in-hours services', () => {
    const counts = limitedOrWorse(board([
      at('limited', '1'), at('not-accepting', '2'), at('over-capacity', '3'),
      at('accepting', '4'), at('not-updated', '5'), at('out-of-hours', '6'),
    ]));
    expect(counts).toEqual({ limited: 3, inHours: 5 });
  });
});

describe('pressureChip', () => {
  it.each([
    ['normal', 'Normal'],
    ['watch', 'Watch'],
    ['high', 'High'],
  ])('shows the word for %s, so the state is not carried by colour alone', (pressure, word) => {
    expect(pressureChip(pressure).word).toBe(word);
    expect(pressureChip(pressure).label).toBeTruthy();
  });
});

describe('attentionLine', () => {
  it('names an over-capacity service by how far over it is, with the time it was reported', () => {
    expect(attentionLine(at('over-capacity', 'a', { overBy: 4, reportedAt: '2026-10-23T12:10:00Z' }), '2026-10-23T13:12:00Z'))
      .toBe('Over capacity +4, reported 13:10');
  });

  it('names a service not accepting by the time it was reported', () => {
    expect(attentionLine(at('not-accepting', 'b', { reportedAt: '2026-10-23T11:50:00Z' }), '2026-10-23T13:12:00Z'))
      .toBe('Not accepting, reported 12:50');
  });

  it('counts a not-updated service in hours and minutes since its last report', () => {
    expect(attentionLine(at('not-updated', 'c', { reportedAt: '2026-10-23T09:02:00Z' }), '2026-10-23T13:12:00Z'))
      .toBe('Not updated for 4 hrs 10 min');
  });
});
