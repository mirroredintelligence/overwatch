// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CSRF_COOKIE, CSRF_HEADER } from '@/lib/auth/csrf';
import { SESSION_COOKIE, sealSession, type Session } from '@/lib/auth/session';
import { askForReview } from '@/lib/register/backend';
import { FhirError } from '@/lib/fhir/client';
import { cookiesMock, requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { POST } from './route';
import { csrfOf } from '@/test/requests';
import { TENANTS } from '@/test/tenants';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});
vi.mock('@/lib/register/backend', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/register/backend')>()),
  askForReview: vi.fn(),
}));

// One of the applicant's actions on the status page (W27). A POST, so it needs the CSRF header; the
// back end's own answer for the action is not built yet, so it is a 503 not-built here.

const ID = 'REG-SAMPLE-1';
// The CSRF token issued to the sample session: bound to its person, tenant and host (TEN-046).
vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
const CSRF = csrfOf(TENANTS.A, 'person-sample-1');
const action = vi.mocked(askForReview);
const url = `https://tenant-a.example.test/api/bff/registrations/${ID}/review-request`;
const ctx = (id: string) => ({ params: Promise.resolve({ id }) });

async function sessionFor(role: Session['role']): Promise<string> {
  return sealSession({ role, tenantId: TENANTS.A.id, host: TENANTS.A.host, services: [], sub: 'person-sample-1', backendToken: 'backend-token-sample-value', expiresAt: new Date(Date.now() + 3_600_000).toISOString() });
}

function call(role: Session['role'] = 'reporter', csrf: string | null = CSRF) {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (csrf !== null) headers[CSRF_HEADER] = csrf;
  return sessionFor(role).then((cookie) =>
    POST(requestWithCookies(url, { [SESSION_COOKIE]: cookie, [CSRF_COOKIE]: CSRF }, { method: 'POST', headers }), ctx(ID)),
  );
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  cookiesMock.mockClear();
  action.mockReset();
  action.mockResolvedValue(undefined);
});

describe('POST /api/bff/registrations/[id]/review-request', () => {
  it('makes the action for this reporter’s registration, and answers 202', async () => {
    const response = await call();
    expect(response.status).toBe(202);
    expect(action).toHaveBeenCalledWith('backend-token-sample-value', ID);
  });

  it('refuses no CSRF header (403) and another role (403), without making the action', async () => {
    expect((await call('reporter', null)).status).toBe(403);
    expect((await call('advisor')).status).toBe(403);
    expect(action).not.toHaveBeenCalled();
  });

  it('answers 503 not-built while the back end has no such route', async () => {
    action.mockRejectedValueOnce(new FhirError(503, { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'not-built', diagnostics: 'x' }] }));
    const response = await call();
    expect(response.status).toBe(503);
    expect(await response.json()).toMatchObject({ code: 'not-built' });
  });
});
