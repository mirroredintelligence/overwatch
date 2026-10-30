import { describe, expect, it } from 'vitest';
import { DECISION_OPEN, DECISION_READY } from '@/test/fixtures/registration';
import type { ScopeEntry } from './types';
import {
  callbackFormError,
  canApprove,
  canInvite,
  categoryLabel,
  decisionNoteError,
  missingText,
  reasonRequired,
  scopeFormError,
  scopeReasonError,
  setLiveEnabled,
} from './model';

const entry = (over: Partial<ScopeEntry> = {}): ScopeEntry => ({
  serviceId: 's3',
  name: 'SDEC · Site 1',
  category: 'same-day-emergency-care',
  flag: 'in-pilot',
  registrationState: 'not-invited',
  ...over,
});

describe('canInvite', () => {
  it('offers an invitation only for an in-pilot service not yet invited', () => {
    expect(canInvite(entry())).toBe(true);
    expect(canInvite(entry({ registrationState: 'in-review' }))).toBe(false);
    expect(canInvite(entry({ registrationState: 'invited' }))).toBe(false);
    expect(canInvite(entry({ flag: 'later' }))).toBe(false);
    expect(canInvite(entry({ flag: 'out-of-scope' }))).toBe(false);
  });
});

describe('reasonRequired and scopeReasonError', () => {
  it('needs a reason for any flag but the pilot', () => {
    expect(reasonRequired('in-pilot')).toBe(false);
    expect(reasonRequired('later')).toBe(true);
    expect(reasonRequired('out-of-scope')).toBe(true);
  });

  it('answers "Enter a reason" for a blank reason that is needed, and nothing otherwise', () => {
    expect(scopeReasonError('out-of-scope', '   ')).toBe('Enter a reason');
    expect(scopeReasonError('out-of-scope', 'Not on the Dorset pathway')).toBeNull();
    expect(scopeReasonError('in-pilot', '')).toBeNull();
  });
});

describe('categoryLabel', () => {
  it('words a known category code and sentence-cases an unknown one without echoing it oddly', () => {
    expect(categoryLabel('urgent-community-response')).toBe('Urgent community response');
    expect(categoryLabel('same-day-emergency-care')).toBe('Same day emergency care');
    expect(categoryLabel('something-new')).toBe('Something new');
  });
});


describe('the call-back and the decision rules (W29)', () => {
  it('needs a role for a confirmed call, and not for the other two results', () => {
    expect(callbackFormError('confirmed', '')).toBe('Enter who you spoke to');
    expect(callbackFormError('confirmed', 'Ward manager')).toBeNull();
    expect(callbackFormError('no-answer', '')).toBeNull();
    expect(callbackFormError('not-confirmed', '  ')).toBeNull();
  });

  it('approves only with nothing missing, and says what is missing in the back end\'s words', () => {
    expect(canApprove(DECISION_OPEN.missing)).toBe(false);
    expect(canApprove([])).toBe(true);
    expect(missingText(['Call-back done', 'Scope decided'])).toBe('Approve is unavailable until: Call-back done, Scope decided');
  });

  it('needs a note to send back or not approve, and never for approve', () => {
    expect(decisionNoteError('send-back', ' ')).toBe('Enter a note for the applicant');
    expect(decisionNoteError('not-approve', '')).toBe('Enter a note for the applicant');
    expect(decisionNoteError('not-approve', 'Out of scope')).toBeNull();
    expect(decisionNoteError('approve', '')).toBeNull();
  });

  it('asks for every scope answer, and a reason unless the decision is the pilot', () => {
    const all = { pathway: 'yes', spoaReferrals: 'no', canReport: 'not-sure', categoryOnList: 'yes' } as const;
    expect(scopeFormError({ pathway: 'yes' }, 'in-pilot', '')).toBe('Answer every question');
    expect(scopeFormError(all, 'out-of-scope', '')).toBe('Enter a reason');
    expect(scopeFormError(all, 'in-pilot', '')).toBeNull();
    expect(scopeFormError(all, null, '')).toBe('Choose a decision');
  });

  it('sets live only once the test is answered', () => {
    expect(setLiveEnabled(DECISION_OPEN)).toBe(false);
    expect(setLiveEnabled({ ...DECISION_OPEN, test: { sentAt: '2026-10-30T16:02:00Z' } })).toBe(false);
    expect(setLiveEnabled(DECISION_READY)).toBe(true);
  });
});
