// Sample registrations and scope entries for the tests. Sample names only, and no patient data.
import type { Decision, Overview, QueueResponse, ScopeEntry } from '@/lib/registration/types';

export const SCOPE_ENTRIES: ScopeEntry[] = [
  { serviceId: 's1', name: 'UCR West', category: 'urgent-community-response', flag: 'in-pilot', registrationState: 'live' },
  { serviceId: 's2', name: 'UCR East', category: 'urgent-community-response', flag: 'in-pilot', registrationState: 'in-review' },
  { serviceId: 's3', name: 'SDEC · Site 1', category: 'same-day-emergency-care', flag: 'in-pilot', registrationState: 'not-invited' },
];

export const QUEUE: QueueResponse = {
  counts: { toReview: 2, waiting: 1, goLive: 1 },
  items: [
    {
      id: 'r1',
      serviceName: 'UCR East',
      state: 'in-review',
      submittedAt: '2026-10-30T14:30:00Z',
      submittedByRole: 'Duty manager',
      firstIssue: 'Criteria owner email is not an organisation address',
    },
    { id: 'r2', serviceName: 'SDEC · Site 1', state: 'in-review', submittedAt: '2026-10-30T13:05:00Z', submittedByRole: 'Duty manager' },
  ],
};

export const OVERVIEW: Overview = {
  id: 'r1',
  serviceName: 'UCR East',
  registeredBy: { name: 'Sample Person', role: 'Duty manager' },
  automaticChecks: [
    { key: 'ods', label: 'ODS code found, active, NHS trust', ok: true },
    { key: 'address', label: 'Address found, in Dorset', ok: true },
    {
      key: 'owner-email',
      label: 'Criteria owner email is not an organisation address',
      ok: false,
      action: 'Ask for an organisation address',
    },
  ],
  manualChecks: { callback: 'not-done', scope: 'not-done', criteria: 'waiting' },
  callBackNumber: '01202 000 111',
};

export const DECISION_OPEN: Decision = {
  missing: ['Automatic checks passed or explained', 'Call-back done', 'Scope decided', 'Criteria second approval (waiting for the clinical lead)'],
  approvedBy: [],
  test: {},
  timeline: [{ at: '2026-10-30T14:30:00Z', label: 'Submitted by Duty manager' }],
};

export const DECISION_READY: Decision = { missing: [], approvedBy: ['Service manager', 'Clinical lead'], test: { sentAt: '2026-10-30T15:02:00Z', answeredAt: '2026-10-30T15:03:00Z' }, timeline: [] };
