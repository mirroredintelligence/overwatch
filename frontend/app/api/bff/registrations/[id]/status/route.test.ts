// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Session } from '@/lib/auth/session';
import { readStatus } from '@/lib/register/backend';
import { FhirError } from '@/lib/fhir/client';
import { cookiesMock, requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { GET } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});
vi.mock('@/lib/register/backend', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/register/backend')>()),
  readStatus: vi.fn(),
}));

// The applicant's status (W27): only the fields the page shows. The back end's other fields, and any
// tenant, stay in the BFF.

const ID = 'REG-SAMPLE-1';
const read = vi.mocked(readStatus);
const url = `https://tenant-a.example.test/api/bff/registrations/${ID}/status`;
const ctx = (id: string) => ({ params: Promise.resolve({ id }) });

async function sessionFor(role: Session['role']): Promise<string> {
  return sealSession({ role, services: [], sub: 'person-sample-1', backendToken: 'backend-token-sample-value', expiresAt: new Date(Date.now() + 3_600_000).toISOString() });
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  cookiesMock.mockClear();
  read.mockReset();
  read.mockResolvedValue({
    status: 'needs-changes',
    serviceName: 'UCR West',
    submittedAt: '2026-10-23T13:30:00Z',
    notes: ['Fix it.'],
    noteFrom: { role: 'SPOA shift lead', at: '2026-10-27T13:52:00Z' },
    details: { spoaPhone: '01305 123456', criteriaOwner: 'Community matron', reportingPhoneEnding: '456', internalRef: 'x' },
    tenantId: 'tenant-b',
  });
});

describe('GET /api/bff/registrations/[id]/status', () => {
  it('answers the reporter with the status and the fields the page shows, and nothing else', async () => {
    const response = await GET(requestWithCookies(url, { [SESSION_COOKIE]: await sessionFor('reporter') }), ctx(ID));
    expect(response.status).toBe(200);
    expect(response.headers.get('Cache-Control')).toBe('no-store');
    const body = (await response.json()) as Record<string, unknown>;
    expect(body).toEqual({
      status: 'needs-changes',
      serviceName: 'UCR West',
      submittedAt: '2026-10-23T13:30:00Z',
      notes: ['Fix it.'],
      noteFrom: { role: 'SPOA shift lead', at: '2026-10-27T13:52:00Z' },
      details: { spoaPhone: '01305 123456', criteriaOwner: 'Community matron', reportingPhoneEnding: '456' },
    });
    expect(JSON.stringify(body)).not.toContain('tenant-b');
    expect(JSON.stringify(body)).not.toContain('internalRef');
  });

  it('refuses no session (401) and another role (403)', async () => {
    expect((await GET(requestWithCookies(url, {}), ctx(ID))).status).toBe(401);
    expect((await GET(requestWithCookies(url, { [SESSION_COOKIE]: await sessionFor('advisor') }), ctx(ID))).status).toBe(403);
    expect(read).not.toHaveBeenCalled();
  });

  it('answers 503 not-built while the back end has no status read', async () => {
    read.mockRejectedValueOnce(new FhirError(503, { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'not-built', diagnostics: 'x' }] }));
    const response = await GET(requestWithCookies(url, { [SESSION_COOKIE]: await sessionFor('reporter') }), ctx(ID));
    expect(response.status).toBe(503);
  });
});
