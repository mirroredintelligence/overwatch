import { describe, expect, it } from 'vitest';
import type { ScopeEntry } from './types';
import { canInvite, categoryLabel, reasonRequired, scopeReasonError } from './model';

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
