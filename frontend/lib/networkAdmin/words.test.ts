import { describe, expect, it } from 'vitest';
import { approvalWord, canEnd, dateText, LISTING_STATUS_WORD, MEMBER_STATUS_WORD, reasonWord, REASON_WORDS, SCOPE_WORD, waitsForOrganisation, waitsForOwner } from './words';
import { GRANT_STATUSES, LISTING_REASONS, LISTING_STATUSES, MEMBER_STATUSES, SCOPES, type GrantStatus } from './views';

const FROM = '2026-10-04T09:00:00Z';
const grant = (status: GrantStatus, effective = false) => ({ status, effective, effectiveFrom: FROM });

describe('the words of the screens', () => {
  it('say every scope, member status and listing status the back end can send', () => {
    expect(Object.keys(SCOPE_WORD).sort()).toEqual([...SCOPES].sort());
    expect(Object.keys(MEMBER_STATUS_WORD).sort()).toEqual([...MEMBER_STATUSES].sort());
    expect(Object.keys(LISTING_STATUS_WORD).sort()).toEqual([...LISTING_STATUSES].sort());
    expect(SCOPES.map((s) => SCOPE_WORD[s])).toEqual(['Capacity', 'Directory', 'Criteria']);
  });

  it('offer exactly the reason codes the back end takes, as the design lists them', () => {
    expect(REASON_WORDS.map(([code]) => code).sort()).toEqual([...LISTING_REASONS].sort());
    expect(REASON_WORDS.map(([, word]) => word)).toEqual(['Outside the area', 'Outside the pilot', 'Duplicate listing', 'Data quality', 'Safety concern', 'Agreement', 'Other']);
    expect(reasonWord('data-quality')).toBe('Data quality');
    expect(reasonWord(null)).toBe('-');
  });

  it('say a date in London time and a missing one as a dash', () => {
    expect(dateText('2026-10-04T23:30:00Z')).toBe('5 Oct 2026'); // an hour past midnight in London (BST)
    expect(dateText(null)).toBe('-');
    expect(dateText('not a date')).toBe('-');
  });
});

describe('the approval of a grant', () => {
  it.each<[GrantStatus, boolean, string]>([
    ['proposed', false, 'Waiting for the organisation and the network owner'],
    ['grantor-approved', false, 'Waiting for the network owner'],
    ['owner-approved', false, 'Waiting for the organisation'],
    ['approved', true, 'Approved'],
    ['approved', false, 'Approved, starts on 4 Oct 2026'],
    ['ended', false, 'Ended'],
    ['lapsed', false, 'Lapsed'],
    ['declined', false, 'Declined'],
    ['superseded', false, 'Replaced by a newer version'],
  ])('%s (effective %s) is "%s"', (status, effective, word) => {
    expect(approvalWord(grant(status, effective))).toBe(word);
  });

  it('is said for every status', () => {
    for (const status of GRANT_STATUSES) expect(approvalWord(grant(status)).length).toBeGreaterThan(0);
  });

  it('lets the owner act only while its own approval is to come, the organisation only while its own is, and an end only while in force', () => {
    expect(GRANT_STATUSES.filter((s) => waitsForOwner({ status: s }))).toEqual(['proposed', 'grantor-approved']);
    expect(GRANT_STATUSES.filter((s) => waitsForOrganisation({ status: s }))).toEqual(['proposed', 'owner-approved']);
    expect(GRANT_STATUSES.filter((s) => canEnd({ status: s }))).toEqual(['approved']);
  });
});
