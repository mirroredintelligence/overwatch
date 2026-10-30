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

// The applicant confirms the details are still right when a re-check is due (W27). The back end
// answers the live status, or 409 unless a re-check is due.

const ID = 'REG-SAMPLE-1';
const url = `https://tenant-a.example.test/api/bff/registrations/${ID}/confirm-details`;
const ctx = (id: string) => ({ params: Promise.resolve({ id }) });

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  resetSeen();
});

describe('POST /api/bff/registrations/[id]/confirm-details', () => {
  it('confirms with a key and answers done', async () => {
    answerBackend('post', `/registrations/${ID}/confirm-details`, 200, { status: 'live', confirmedAt: '2026-10-30T10:00:00Z' });
    const response = await POST(await callerRequest(url, 'reporter', { method: 'POST' }), ctx(ID));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ done: true });
    expect(seen[0]?.idem).toMatch(/^[0-9a-f-]{36}$/);
  });

  it('answers 409 when no re-check is due', async () => {
    answerBackend('post', `/registrations/${ID}/confirm-details`, 409, { resourceType: 'OperationOutcome', issue: [] });
    const response = await POST(await callerRequest(url, 'reporter', { method: 'POST' }), ctx(ID));
    expect(response.status).toBe(409);
  });
});
