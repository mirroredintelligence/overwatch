import { describe, expect, it } from 'vitest';
import { criteriaOverviewFromBackend, pendingFromBackend } from './mapping';

// The owner's and the approver's criteria reads, mapped from the back end's answers (W7B A4,
// routes_criteria_views.py) to the shapes the criteria pages use (DEC-908). A criteria value is the
// version's own; a version's author is a role, never a person's name; nothing else is kept.

const CURRENT = {
  id: 'CRIT-1',
  version: 3,
  status: 'current',
  reviewBy: '2027-01-31',
  ageMin: 18,
  ageMax: null,
  accepts: [{ code: 'frailty', label: 'Frailty' }],
  excludes: [{ code: 'palliative', label: 'Palliative care' }],
  districts: ['DT4', 'DT5'],
  changedOn: '2026-10-01T09:00:00Z',
  authorRole: 'Criteria owner',
};

const OVERVIEW = {
  serviceId: 'SVC-1',
  serviceName: 'Community nursing',
  current: CURRENT,
  draft: null,
  pending: null,
  overdue: false,
  overdueSince: null,
  shiftLead: { label: 'Shift lead', phone: '01305 000111' },
  isOwner: true,
};

describe('criteriaOverviewFromBackend', () => {
  it('gives the current version’s values as codes, its version and its review date, and the shift lead', () => {
    expect(criteriaOverviewFromBackend(OVERVIEW)).toEqual({
      serviceName: 'Community nursing',
      current: {
        version: 3,
        reviewBy: '2027-01-31',
        accepts: ['frailty'],
        excludes: ['palliative'],
        ageMin: 18,
        ageMax: null,
        districts: ['DT4', 'DT5'],
      },
      shiftLead: { role: 'Shift lead', phone: '01305 000111' },
    });
  });

  it('shows a version the approver sent back as the draft, with its reason and the day it was made', () => {
    const view = criteriaOverviewFromBackend({
      ...OVERVIEW,
      draft: { ...CURRENT, id: 'CRIT-4', version: 4, status: 'draft', changeReason: 'Frailty pathway added', changedOn: '2026-10-29T09:00:00Z' },
    });
    expect(view?.draft).toMatchObject({ version: 4, status: 'sent-back', note: 'Frailty pathway added', sentAt: '2026-10-29T09:00:00Z', accepts: ['frailty'] });
  });

  it('shows a version waiting for approval as the draft with the waiting status', () => {
    const view = criteriaOverviewFromBackend({
      ...OVERVIEW,
      pending: { id: 'CRIT-5', version: 5, changeReason: 'Review', changedOn: '2026-10-30T09:00:00Z' },
    });
    expect(view?.draft).toMatchObject({ version: 5, status: 'waiting', sentAt: '2026-10-30T09:00:00Z' });
  });

  it('gives the overdue day when the review date has passed, and nothing when it has not', () => {
    expect(criteriaOverviewFromBackend({ ...OVERVIEW, overdue: true, overdueSince: '2026-10-01' })?.overdueSince).toBe('2026-10-01');
    expect(criteriaOverviewFromBackend(OVERVIEW)?.overdueSince).toBeUndefined();
  });

  it('never passes a person’s name or the author’s identity, only the role', () => {
    const text = JSON.stringify(criteriaOverviewFromBackend({ ...OVERVIEW, current: { ...CURRENT, authorName: 'Sam Sample', authorId: 'person-1' } }));
    expect(text).not.toContain('Sam Sample');
    expect(text).not.toContain('person-1');
  });

  it('is null for an answer with no current version', () => {
    expect(criteriaOverviewFromBackend({ serviceName: 'x' })).toBeNull();
  });
});

const PENDING = {
  criteriaId: 'CRIT-5',
  serviceId: 'SVC-1',
  serviceName: 'Community nursing',
  version: 5,
  status: 'waiting',
  changeReason: 'Frailty pathway added',
  authorRole: 'Criteria owner',
  isAuthor: false,
  reviewMonths: 6,
  changedOn: '2026-10-30T09:00:00Z',
  criteria: { ageMin: 18, ageMax: null, accepts: [{ code: 'frailty', label: 'Frailty' }], excludes: [], districts: ['DT4'], reviewBy: '2027-04-30' },
  changes: [{ field: 'accepts', label: 'Accepts', before: [], after: ['frailty'], words: 'Accepts frailty' }],
};

describe('pendingFromBackend', () => {
  it('gives the change as words, the reason and the author’s role, and whether the approver wrote it', () => {
    expect(pendingFromBackend(PENDING)).toEqual({
      serviceName: 'Community nursing',
      taskId: 'CRIT-5',
      isAuthor: false,
      changes: ['Accepts frailty'],
      reason: 'Frailty pathway added',
      authorRole: 'Criteria owner',
    });
  });

  it('gives the whole of the criteria, and no list of changes, when there is no earlier version', () => {
    const view = pendingFromBackend({ ...PENDING, changes: null });
    expect(view?.changes).toBeNull();
    expect(view?.full).toMatchObject({ version: 5, reviewBy: '2027-04-30', accepts: ['frailty'], districts: ['DT4'], ageMin: 18 });
  });

  it('is null for an answer with no criteria id', () => {
    expect(pendingFromBackend({ serviceName: 'x' })).toBeNull();
  });
});
