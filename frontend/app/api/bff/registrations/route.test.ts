// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BACKEND_ROOT } from '@/test/fixtures/links';
import { answerBackend, breakBackend, resetSeen, seen } from '@/test/applicant/backend';
import { callerRequest } from '@/test/applicant/session';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { withApplicantHandlers } from '@/test/msw/applicant';
import { GET } from './route';

withApplicantHandlers();

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

// The registrations queue (W28): the back end's tabs, their counts and one tab's rows, for the shift
// lead. The default tab is waiting. A tab the back end does not have is a 400 and calls nothing.

const url = (query: string) => `https://tenant-a.example.test/api/bff/registrations${query}`;
const ANSWER = {
  tab: 'waiting',
  counts: { waiting: 1, 'sent-back': 0, approved: 0, live: 1, 'not-approved': 0 },
  tabs: [
    { key: 'waiting', label: 'Waiting', count: 1 },
    { key: 'sent-back', label: 'Sent back', count: 0 },
    { key: 'approved', label: 'Approved', count: 0 },
    { key: 'live', label: 'Live', count: 1 },
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
    },
  ],
};

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  resetSeen();
});

describe('GET /api/bff/registrations (the queue)', () => {
  it('defaults to the waiting tab, and answers the tabs, their counts and the rows', async () => {
    answerBackend('get', '/registrations', 200, ANSWER);
    const response = await GET(await callerRequest(url(''), 'lead'));
    expect(response.status).toBe(200);
    const body = (await response.json()) as { tab: string; counts: Record<string, number>; items: unknown[] };
    expect(body).toMatchObject({ tab: 'waiting', counts: { waiting: 1, live: 1 } });
    expect(body.items).toEqual([
      { id: 'REG-1', serviceName: 'Community nursing', state: 'submitted', submittedAt: '2026-10-29T09:00:00Z', submittedByRole: 'Duty manager', category: 'urgent-community-response' },
    ]);
    expect(seen[0]).toMatchObject({ path: '/registrations', auth: 'Bearer backend-token-sample-value' });
  });

  it('asks the back end for the tab it is given', async () => {
    answerBackend('get', '/registrations', 200, { ...ANSWER, tab: 'live' });
    await GET(await callerRequest(url('?tab=live'), 'lead'));
    expect(seen[0]?.path).toBe('/registrations');
  });

  it('refuses a tab the back end does not have, without calling it', async () => {
    const response = await GET(await callerRequest(url('?tab=to-review'), 'lead'));
    expect(response.status).toBe(400);
    expect(seen).toHaveLength(0);
  });

  it('answers 503 when the back end answers a queue the page cannot read', async () => {
    answerBackend('get', '/registrations', 200, { tab: 'waiting' });
    const response = await GET(await callerRequest(url(''), 'lead'));
    expect(response.status).toBe(503);
  });

  it('answers 503 when the back end cannot be reached', async () => {
    breakBackend('get', '/registrations');
    expect((await GET(await callerRequest(url(''), 'lead'))).status).toBe(503);
  });

  it('refuses the applicant, who has no queue', async () => {
    expect((await GET(await callerRequest(url(''), 'reporter'))).status).toBe(403);
    expect(seen).toHaveLength(0);
  });
});
