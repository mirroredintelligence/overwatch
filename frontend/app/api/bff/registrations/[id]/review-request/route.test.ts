// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BACKEND_ROOT } from '@/test/fixtures/links';
import { answerBackend, resetSeen, seen } from '@/test/applicant/backend';
import { callerRequest } from '@/test/applicant/session';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { withApplicantHandlers } from '@/test/msw/applicant';
import { POST } from './route';

withApplicantHandlers();

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

// Ask the shift lead to look again (W27). The back end allows it only once submitted or in review.

const ID = 'REG-SAMPLE-1';
const url = `https://tenant-a.example.test/api/bff/registrations/${ID}/review-request`;
const ctx = (id: string) => ({ params: Promise.resolve({ id }) });

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  resetSeen();
});

describe('POST /api/bff/registrations/[id]/review-request', () => {
  it('asks the back end for a review with a key and answers 202 done', async () => {
    answerBackend('post', `/registrations/${ID}/review-request`, 200, { requestedAt: '2026-10-30T10:00:00Z' });
    const response = await POST(await callerRequest(url, 'reporter', { method: 'POST' }), ctx(ID));
    expect(response.status).toBe(202);
    expect(await response.json()).toEqual({ done: true });
    expect(seen[0]).toMatchObject({ path: `/registrations/${ID}/review-request`, auth: 'Bearer backend-token-sample-value' });
    expect(seen[0]?.idem).toMatch(/^[0-9a-f-]{36}$/);
  });

  it('answers the back end’s 409 as 409 when the registration is not waiting for a review', async () => {
    answerBackend('post', `/registrations/${ID}/review-request`, 409, { resourceType: 'OperationOutcome', issue: [] });
    const response = await POST(await callerRequest(url, 'reporter', { method: 'POST' }), ctx(ID));
    expect(response.status).toBe(409);
  });
});
