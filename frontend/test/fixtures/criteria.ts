// Sample criteria for the tests (sample service names only, no patient data). Dates are ISO days.
import type { CriteriaOverview } from '@/lib/criteria/types';

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
