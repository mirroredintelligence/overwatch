// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BACKEND_ROOT } from '@/test/fixtures/links';
import { answerBackend, resetSeen, seen } from '@/test/applicant/backend';
import { callerRequest } from '@/test/applicant/session';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { withApplicantHandlers } from '@/test/msw/applicant';
import { GET } from './route';

withApplicantHandlers();

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

// What is missing before a decision, who has approved, the test, and the timeline (W29, check 4 of 4).
// Lead only: the back end's decision read, mapped for the page.

const ID = 'REG-SAMPLE-1';
const url = `https://tenant-a.example.test/api/bff/registrations/${ID}/decision`;
const ctx = (id: string) => ({ params: Promise.resolve({ id }) });

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  resetSeen();
});

describe('GET /api/bff/registrations/[id]/decision', () => {
  it('reads the decision with the lead’s token and answers what the page shows', async () => {
    answerBackend('get', `/registrations/${ID}/decision`, 200, {
      registrationId: ID,
      status: 'in-review',
      missing: ['The call-back is not confirmed'],
      approvals: [{ key: 'shift-lead', label: 'Shift lead', done: true }],
      canApprove: false,
      test: { sentAt: '2026-10-29T10:00:00Z', channel: 'text' },
      timeline: [{ event: 'Submitted', at: '2026-10-29T09:00:00Z' }],
    });
    const response = await GET(await callerRequest(url, 'lead'), ctx(ID));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      missing: ['The call-back is not confirmed'],
      approvedBy: ['Shift lead'],
      test: { sentAt: '2026-10-29T10:00:00Z' },
      timeline: [{ at: '2026-10-29T09:00:00Z', label: 'Submitted' }],
    });
    expect(seen[0]).toMatchObject({ path: `/registrations/${ID}/decision`, auth: 'Bearer backend-token-sample-value' });
  });

  it('refuses the applicant, without calling the back end', async () => {
    expect((await GET(await callerRequest(url, 'reporter'), ctx(ID))).status).toBe(403);
    expect(seen).toHaveLength(0);
  });
});
