// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Session } from '@/lib/auth/session';
import { readReview } from '@/lib/register/backend';
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
  readReview: vi.fn(),
}));

// The review of a registration (W26): one row per section, complete or needing attention, with the
// words the back end gives. Nothing else the back end holds leaves the BFF.

const ID = 'REG-SAMPLE-1';
const read = vi.mocked(readReview);
const url = `https://tenant-a.example.test/api/bff/registrations/${ID}/review`;
const ctx = (id: string) => ({ params: Promise.resolve({ id }) });

async function sessionFor(role: Session['role']): Promise<string> {
  return sealSession({ role, tenantId: TENANTS.A.id, host: TENANTS.A.host, services: [], sub: 'person-sample-1', backendToken: 'backend-token-sample-value', expiresAt: new Date(Date.now() + 3_600_000).toISOString() });
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  cookiesMock.mockClear();
  read.mockReset();
  read.mockResolvedValue([
    { key: 'organisation', status: 'complete', summary: 'Sample Community Trust', checkedBy: 'lead' },
    { key: 'service', status: 'needs-attention', summary: 'UCR West · criteria review date missing' },
  ] as never);
});

describe('GET /api/bff/registrations/[id]/review', () => {
  it('answers a reporter with the sections, their status and summary, and nothing else', async () => {
    const response = await GET(requestWithCookies(url, { [SESSION_COOKIE]: await sessionFor('reporter') }), ctx(ID));
    expect(response.status).toBe(200);
    expect(response.headers.get('Cache-Control')).toBe('private, no-store');
    expect(await response.json()).toEqual({
      sections: [
        { key: 'organisation', status: 'complete', summary: 'Sample Community Trust' },
        { key: 'service', status: 'needs-attention', summary: 'UCR West · criteria review date missing' },
      ],
    });
    expect(read).toHaveBeenCalledWith('backend-token-sample-value', ID);
  });

  it('refuses no session (401) and another role (403)', async () => {
    expect((await GET(requestWithCookies(url, {}), ctx(ID))).status).toBe(401);
    expect((await GET(requestWithCookies(url, { [SESSION_COOKIE]: await sessionFor('lead') }), ctx(ID))).status).toBe(403);
    expect(read).not.toHaveBeenCalled();
  });

  it('answers 503 not-built while the back end has no review read', async () => {
    read.mockRejectedValueOnce(new FhirError(503, { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'not-built', diagnostics: 'x' }] }));
    const response = await GET(requestWithCookies(url, { [SESSION_COOKIE]: await sessionFor('reporter') }), ctx(ID));
    expect(response.status).toBe(503);
    expect(await response.json()).toMatchObject({ code: 'not-built' });
  });
});
