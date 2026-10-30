// Sample criteria for the tests (sample service names only, no patient data). Dates are ISO days.
import type { CriteriaOverview, HistoryVersion, PendingChange } from '@/lib/criteria/types';

export const CRITERIA_OVERVIEW: CriteriaOverview = {
  serviceName: 'UCR West',
  current: {
    version: 3,
    accepts: ['fall-no-injury', 'frailty'],
    excludes: ['suspected-fracture', 'head-injury-anticoagulants'],
    ageMin: 18,
    ageMax: null,
    districts: ['DT1', 'DT2', 'DT3', 'DT4'],
    reviewBy: '2026-12-12',
  },
};

export const CRITERIA_OVERVIEW_WAITING: CriteriaOverview = {
  ...CRITERIA_OVERVIEW,
  draft: {
    version: 4,
    accepts: ['fall-no-injury', 'frailty', 'dementia'],
    excludes: ['suspected-fracture', 'head-injury-anticoagulants'],
    ageMin: 16,
    ageMax: null,
    districts: ['DT1', 'DT2', 'DT3', 'DT4'],
    reviewBy: '2026-12-12',
    status: 'waiting',
    sentAt: '2026-10-30T14:02:00Z',
  },
};

export const PENDING_CHANGE: PendingChange = {
  serviceName: 'UCR West',
  taskId: 'basic-4',
  isAuthor: false,
  changes: ['Youngest age 18 to 16'],
  reason: 'Younger patients can be seen',
  authorRole: 'Criteria owner',
};

export const PENDING_REGISTRATION: PendingChange = {
  serviceName: 'UCR East',
  taskId: 'basic-1',
  isAuthor: false,
  changes: null,
  full: {
    accepts: ['fall-no-injury', 'frailty'],
    excludes: ['suspected-fracture'],
    ageMin: 18,
    ageMax: null,
    districts: ['DT3', 'DT4'],
    reviewBy: '2027-04-30',
    version: 1,
    ownerRole: 'Criteria owner',
  },
  reason: '',
  authorRole: 'Duty manager',
};

export const HISTORY: { versions: HistoryVersion[] } = {
  versions: [
    { version: 4, status: 'waiting', reviewBy: '2026-12-12', criteriaId: 'basic-4' },
    { version: 3, status: 'current', reviewBy: '2026-09-12', criteriaId: 'basic-3' },
    { version: 2, status: 'replaced', reviewBy: '2026-06-24', criteriaId: 'basic-2' },
    { version: 1, status: 'replaced', reviewBy: '2026-03-01', criteriaId: 'basic-1' },
  ],
};
