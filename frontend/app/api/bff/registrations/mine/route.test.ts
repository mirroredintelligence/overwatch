// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Session } from '@/lib/auth/session';
import { readMine } from '@/lib/register/backend';
import { FhirError } from '@/lib/fhir/client';
import { cookiesMock, requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { GET } from './route';
import { TENANTS } from '@/test/tenants';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});
vi.mock('@/lib/register/backend', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/register/backend')>()),
  readMine: vi.fn(),
}));

// My services (W26): the reporter's own services and where each stands, in the words the page shows.

const read = vi.mocked(readMine);
const url = 'https://tenant-a.example.test/api/bff/registrations/mine';

async function sessionFor(role: Session['role']): Promise<string> {
  return sealSession({ role, tenantId: TENANTS.A.id, host: TENANTS.A.host, services: [], sub: 'person-sample-1', backendToken: 'backend-token-sample-value', expiresAt: new Date(Date.now() + 3_600_000).toISOString() });
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  cookiesMock.mockClear();
  read.mockReset();
  read.mockResolvedValue([
    { id: 'REG-SAMPLE-1', serviceName: 'UCR West', state: 'active', detail: 'Reporting every 2 hrs by text', tenantId: 'tenant-b' },
  ] as never);
});

describe('GET /api/bff/registrations/mine', () => {
  it('answers the reporter’s services with their state and detail, and no other field', async () => {
    const response = await GET(requestWithCookies(url, { [SESSION_COOKIE]: await sessionFor('reporter') }));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      services: [{ id: 'REG-SAMPLE-1', serviceName: 'UCR West', state: 'active', detail: 'Reporting every 2 hrs by text' }],
    });
    expect(read).toHaveBeenCalledWith('backend-token-sample-value');
  });

  it('refuses no session (401) and another role (403)', async () => {
    expect((await GET(requestWithCookies(url, {}))).status).toBe(401);
    expect((await GET(requestWithCookies(url, { [SESSION_COOKIE]: await sessionFor('exec') }))).status).toBe(403);
  });

  it('answers 503 not-built while the back end has no list of a reporter’s services', async () => {
    read.mockRejectedValueOnce(new FhirError(503, { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'not-built', diagnostics: 'x' }] }));
    const response = await GET(requestWithCookies(url, { [SESSION_COOKIE]: await sessionFor('reporter') }));
    expect(response.status).toBe(503);
  });
});
