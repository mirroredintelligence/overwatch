import { describe, expect, it } from 'vitest';
import { decisionFromBackend, overviewFromBackend, queueFromBackend } from './mapping';

// The reviewer's reads, mapped from the back end's answers (W7B A4, routes_registration_views.py) to the
// shapes the reviewer's pages use (DEC-907). The queue has the back end's own tabs and counts; the
// overview's checks come from the back end's review, and the call-back number is never invented: the
// back end gives none, so none is passed (a known issue, K-W8C-2). Sample values only.

const QUEUE = {
  tab: 'waiting',
  counts: { waiting: 2, 'sent-back': 1, approved: 0, live: 4, 'not-approved': 0 },
  tabs: [
    { key: 'waiting', label: 'Waiting', count: 2 },
    { key: 'sent-back', label: 'Sent back', count: 1 },
    { key: 'approved', label: 'Approved', count: 0 },
    { key: 'live', label: 'Live', count: 4 },
    { key: 'not-approved', label: 'Not approved', count: 0 },
  ],
  registrations: [
    {
      registrationId: 'REG-1',
      serviceId: 'SVC-1',
      serviceName: 'Community nursing',
      category: 'urgent-community-response',
      status: 'submitted',
      submittedAt: '2026-10-29T09:00:00Z',
      registeredBy: { role: 'Duty manager', contactName: 'Sam Sample' },
      reviewRequestedAt: null,
      tenantId: 'tenant-a',
    },
  ],
};

describe('queueFromBackend', () => {
  it('keeps the back end’s tabs, their counts and the rows the page shows, and nothing else', () => {
    const queue = queueFromBackend(QUEUE);
    expect(queue).toEqual({
      tab: 'waiting',
      counts: { waiting: 2, 'sent-back': 1, approved: 0, live: 4, 'not-approved': 0 },
      tabs: QUEUE.tabs,
      items: [
        {
          id: 'REG-1',
          serviceName: 'Community nursing',
          state: 'submitted',
          submittedAt: '2026-10-29T09:00:00Z',
          submittedByRole: 'Duty manager',
          category: 'urgent-community-response',
        },
      ],
    });
    expect(JSON.stringify(queue)).not.toContain('tenant-a');
  });

  it('is null for an answer with an unknown tab or no rows', () => {
    expect(queueFromBackend({ ...QUEUE, tab: 'to-review' })).toBeNull();
    expect(queueFromBackend({ ...QUEUE, registrations: undefined })).toBeNull();
  });
});

const OVERVIEW = {
  registrationId: 'REG-1',
  status: 'in-review',
  serviceId: 'SVC-1',
  serviceName: 'Community nursing',
  category: 'urgent-community-response',
  checks: [
    { name: 'ods', passed: true, ok: true, message: 'The ODS code is on the register', explainedNote: null },
    { name: 'phone', passed: false, ok: false, message: 'The callback number does not match', explainedNote: 'Checked with the applicant' },
  ],
  automaticOk: false,
  callbackConfirmed: false,
  scope: null,
  criteriaApproved: false,
  missing: ['The call-back is not confirmed', 'The scope is not decided'],
  registeredBy: { role: 'Duty manager', contactName: 'Sam Sample', organisationName: 'Sample Community Trust' },
  applicantNumbers: [{ label: 'Reporting', ending: '456' }],
  callBack: { numberToCall: null, directoryName: 'the area directory', pathwayName: 'Urgent community response pathway' },
};

describe('overviewFromBackend', () => {
  it('gives the checks, the manual checks as done or not, the words of the call-back and the pathway', () => {
    const overview = overviewFromBackend(OVERVIEW);
    expect(overview).toMatchObject({
      id: 'REG-1',
      serviceName: 'Community nursing',
      registeredBy: { name: 'Sam Sample', role: 'Duty manager' },
      automaticChecks: [
        { key: 'ods', label: 'The ODS code is on the register', ok: true },
        { key: 'phone', label: 'The callback number does not match', ok: false, action: 'Checked with the applicant' },
      ],
      manualChecks: { callback: 'not-done', scope: 'not-done', criteria: 'not-done' },
      pathwayName: 'Urgent community response pathway',
      callBack: { directoryName: 'the area directory' },
    });
    expect(overview?.callBack).not.toHaveProperty('numberToCall');
  });

  it('marks the call-back, scope and criteria done when the back end says so', () => {
    const overview = overviewFromBackend({ ...OVERVIEW, callbackConfirmed: true, scope: 'in-pilot', criteriaApproved: true });
    expect(overview?.manualChecks).toEqual({ callback: 'done', scope: 'done', criteria: 'done' });
  });

  it('never passes a phone number, an organisation name or an applicant number', () => {
    const text = JSON.stringify(overviewFromBackend({ ...OVERVIEW, registeredBy: { ...OVERVIEW.registeredBy, contactPhone: '07700900456' } }));
    expect(text).not.toContain('07700900456');
    expect(text).not.toContain('Sample Community Trust');
    expect(text).not.toContain('456');
  });

  it('is null for an answer that is not an overview', () => {
    expect(overviewFromBackend({ registrationId: 'REG-1' })).toBeNull();
  });
});

describe('decisionFromBackend', () => {
  it('gives what is missing, who has approved, the test, and the timeline in the page’s words', () => {
    const decision = decisionFromBackend({
      registrationId: 'REG-1',
      status: 'in-review',
      missing: ['The call-back is not confirmed'],
      approvals: [
        { key: 'shift-lead', label: 'Shift lead', done: true },
        { key: 'clinical', label: 'Clinical lead', done: false },
      ],
      canApprove: false,
      test: { sentAt: '2026-10-29T10:00:00Z', channel: 'text' },
      timeline: [{ event: 'Submitted', at: '2026-10-29T09:00:00Z' }],
    });
    expect(decision).toEqual({
      missing: ['The call-back is not confirmed'],
      approvedBy: ['Shift lead'],
      test: { sentAt: '2026-10-29T10:00:00Z' },
      timeline: [{ at: '2026-10-29T09:00:00Z', label: 'Submitted' }],
    });
  });

  it('is null for an answer with no approvals list', () => {
    expect(decisionFromBackend({ missing: [] })).toBeNull();
  });
});
