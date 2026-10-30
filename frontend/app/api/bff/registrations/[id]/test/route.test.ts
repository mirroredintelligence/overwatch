// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BACKEND_ROOT } from '@/test/fixtures/links';
import { answerBackend, breakBackend, resetSeen, seen } from '@/test/applicant/backend';
import { callerRequest } from '@/test/applicant/session';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { withApplicantHandlers } from '@/test/msw/applicant';
import { POST } from './route';

withApplicantHandlers();

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

// The test notification (W27 for the applicant; the lead sends it again at go live, W29). The back end
// sends it once a minute at most, after submission, and answers 409 when that is not allowed.

const ID = 'REG-SAMPLE-1';
const url = `https://tenant-a.example.test/api/bff/registrations/${ID}/test`;
const ctx = (id: string) => ({ params: Promise.resolve({ id }) });

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  resetSeen();
});

describe('POST /api/bff/registrations/[id]/test', () => {
  it('sends the test with a idempotency key and the bearer token, and answers done', async () => {
    answerBackend('post', `/registrations/${ID}/test-notification`, 200, { sentAt: '2026-10-30T10:00:00Z', channel: 'text' });
    const response = await POST(await callerRequest(url, 'reporter', { method: 'POST', idempotencyKey: 'k-1' }), ctx(ID));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ done: true });
    expect(seen[0]).toMatchObject({ path: `/registrations/${ID}/test-notification`, auth: 'Bearer backend-token-sample-value' });
    expect(seen[0]?.idem).toMatch(/^[0-9a-f-]{36}$/);
  });

  it('answers the back end’s 409 as 409, with the words it gives, when a test is too soon', async () => {
    answerBackend('post', `/registrations/${ID}/test-notification`, 409, { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'conflict', diagnostics: 'A test was sent a minute ago' }] });
    const response = await POST(await callerRequest(url, 'reporter', { method: 'POST' }), ctx(ID));
    expect(response.status).toBe(409);
    expect(await response.json()).toMatchObject({ code: 'conflict' });
  });

  it('answers 503 when the back end cannot be reached', async () => {
    breakBackend('post', `/registrations/${ID}/test-notification`);
    const response = await POST(await callerRequest(url, 'reporter', { method: 'POST' }), ctx(ID));
    expect(response.status).toBe(503);
  });

  it('refuses a post with no CSRF token before the back end is called', async () => {
    const response = await POST(await callerRequest(url, 'reporter', { method: 'POST', csrf: false }), ctx(ID));
    expect(response.status).toBe(403);
    expect(seen).toHaveLength(0);
  });
});
