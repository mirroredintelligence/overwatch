import { describe, expect, it } from 'vitest';
import { arrivalWord, cardFor, cardWord, windowWord } from './sharing';
import type { GrantRow, GrantStatus, KindState, Scope } from './views';

const grant = (id: string, scope: Scope, status: GrantStatus, over: Partial<GrantRow> = {}): GrantRow => ({
  id,
  organisation: 'Sample Area A',
  scope,
  status,
  version: 1,
  effectiveFrom: '2026-10-04T09:00:00Z',
  effectiveTo: null,
  agreementVersion: 1,
  allowlistVersion: 1,
  grantorApprovedAt: null,
  ownerApprovedAt: null,
  endedAt: null,
  endReason: null,
  effective: false,
  ...over,
});
const ended = (id: string, status: 'ended' | 'lapsed' | 'superseded', at: string, over: Partial<GrantRow> = {}) =>
  grant(id, 'capacity', status, { endedAt: at, endReason: status, ...over });

describe('the card of a kind (design N2: SharingOverview)', () => {
  it('is Not sharing when nothing was ever proposed', () => {
    const card = cardFor('capacity', [], []);
    expect(card.state).toEqual({ kind: 'not-sharing' });
    expect(cardWord(card.state)).toBe('Not sharing');
    expect(card.waitingFor).toBeNull();
    expect(card.endable).toBeNull();
  });

  it('waits for the organisation’s own approval while the owner’s may be given or not: the organisation acts', () => {
    for (const status of ['proposed', 'owner-approved'] as const) {
      const card = cardFor('capacity', [grant('g1', 'capacity', status)], []);
      expect(card.state).toEqual({ kind: 'waiting-you' });
      expect(card.waitingFor).toBe('g1');
      expect(cardWord(card.state)).toBe('Waiting for your approval');
    }
  });

  it('waits for the network owner once the organisation has approved', () => {
    const card = cardFor('capacity', [grant('g1', 'capacity', 'grantor-approved')], []);
    expect(card.state).toEqual({ kind: 'waiting-owner' });
    expect(card.waitingFor).toBeNull();
    expect(cardWord(card.state)).toBe('Waiting for the network owner');
  });

  it('is Sharing since the start of the window when it is approved and in force, and can be ended', () => {
    const card = cardFor('capacity', [grant('g1', 'capacity', 'approved', { effective: true })], []);
    expect(card.state).toEqual({ kind: 'sharing', since: '2026-10-04T09:00:00Z' });
    expect(cardWord(card.state)).toBe('Sharing since 4 Oct 2026');
    expect(card.endable).toBe('g1');
  });

  it('says an approved grant that has not started has not started, and can still be ended', () => {
    const card = cardFor('capacity', [grant('g1', 'capacity', 'approved', { effective: false })], []);
    expect(card.state).toEqual({ kind: 'scheduled', from: '2026-10-04T09:00:00Z' });
    expect(cardWord(card.state)).toBe('Approved. Sharing starts on 4 Oct 2026');
    expect(card.endable).toBe('g1');
  });

  it.each(['ended', 'lapsed', 'superseded'] as const)('is Ended on the date a %s grant ended', (status) => {
    const card = cardFor('capacity', [ended('g1', status, '2026-10-20T09:00:00Z')], []);
    expect(card.state).toEqual({ kind: 'ended', on: '2026-10-20T09:00:00Z' });
    expect(cardWord(card.state)).toBe('Ended on 20 Oct 2026');
    expect(card.endable).toBeNull();
  });

  it('is Not sharing, not Ended, for a grant that was declined', () => {
    expect(cardFor('capacity', [grant('g1', 'capacity', 'declined')], []).state).toEqual({ kind: 'not-sharing' });
  });

  it('shows the latest ending when there are several', () => {
    const card = cardFor('capacity', [ended('g1', 'ended', '2026-10-10T09:00:00Z'), ended('g2', 'lapsed', '2026-10-25T09:00:00Z', { version: 2 })], []);
    expect(card.state).toEqual({ kind: 'ended', on: '2026-10-25T09:00:00Z' });
  });

  it('puts what needs the organisation first: a revision waiting for approval shows over the one in force, which is still said', () => {
    const card = cardFor(
      'capacity',
      [grant('g1', 'capacity', 'approved', { effective: true }), grant('g2', 'capacity', 'proposed', { version: 2 })],
      [],
    );
    expect(card.state).toEqual({ kind: 'waiting-you' });
    expect(card.waitingFor).toBe('g2');
    expect(card.inForceSince).toBe('2026-10-04T09:00:00Z');
    expect(card.endable).toBeNull();
  });

  it('reads only the grants of its own kind', () => {
    const card = cardFor('directory', [grant('g1', 'capacity', 'approved', { effective: true })], []);
    expect(card.state).toEqual({ kind: 'not-sharing' });
  });
});

describe('what has reached the network', () => {
  const kind = (scope: Scope, status: 'active' | 'ended', endedAt: string | null = null): KindState => ({ kind: scope, status, endedAt, endReason: endedAt === null ? null : 'grant-ended' });

  it('says it is receiving what is open, for that kind only', () => {
    const card = cardFor('capacity', [grant('g1', 'capacity', 'approved', { effective: true })], [kind('capacity', 'active'), kind('directory', 'ended', '2026-10-01T00:00:00Z')]);
    expect(card.arrival).toEqual({ kind: 'receiving' });
    expect(arrivalWord(card)).toBe('The network is receiving this.');
  });

  it('says nothing has arrived yet for a grant in force with nothing open', () => {
    const card = cardFor('capacity', [grant('g1', 'capacity', 'approved', { effective: true })], []);
    expect(arrivalWord(card)).toBe('Nothing has arrived on the network yet.');
  });

  it('says when the network stopped receiving it', () => {
    const card = cardFor('directory', [ended('g1', 'ended', '2026-10-29T10:00:00Z', { scope: 'directory' })], [kind('directory', 'ended', '2026-10-29T10:00:00Z')]);
    expect(card.arrival).toEqual({ kind: 'stopped', at: '2026-10-29T10:00:00Z' });
    expect(arrivalWord(card)).toBe('The network stopped receiving this on 29 Oct 2026.');
  });

  it('says nothing about arrival for a kind that was never shared', () => {
    expect(arrivalWord(cardFor('criteria', [], []))).toBeNull();
  });
});

describe('the window of the grant the card is about', () => {
  it('is said for a grant in force, with or without an end', () => {
    const open = cardFor('capacity', [grant('g1', 'capacity', 'approved', { effective: true })], []);
    expect(open.window).toEqual({ from: '2026-10-04T09:00:00Z', to: null });
    expect(windowWord(open)).toBe('From 4 Oct 2026, no end date');
    const dated = cardFor('capacity', [grant('g1', 'capacity', 'approved', { effective: true, effectiveTo: '2026-11-30T09:00:00Z' })], []);
    expect(windowWord(dated)).toBe('From 4 Oct 2026 to 30 Nov 2026');
  });

  it('is said for a grant that waits, so an administrator sees what they would approve', () => {
    expect(windowWord(cardFor('capacity', [grant('g1', 'capacity', 'proposed', { effectiveTo: '2026-11-30T09:00:00Z' })], []))).toBe('From 4 Oct 2026 to 30 Nov 2026');
    expect(windowWord(cardFor('capacity', [grant('g1', 'capacity', 'grantor-approved')], []))).toBe('From 4 Oct 2026, no end date');
  });

  it('is the one that waits when a newer version waits over one in force', () => {
    const card = cardFor('capacity', [grant('g1', 'capacity', 'approved', { effective: true }), grant('g2', 'capacity', 'proposed', { version: 2, effectiveFrom: '2026-12-01T09:00:00Z' })], []);
    expect(card.window).toEqual({ from: '2026-12-01T09:00:00Z', to: null });
  });

  it('is nothing for a kind that is not shared, or ended', () => {
    expect(windowWord(cardFor('criteria', [], []))).toBeNull();
    expect(windowWord(cardFor('capacity', [ended('g1', 'ended', '2026-10-20T09:00:00Z')], []))).toBeNull();
  });
});
