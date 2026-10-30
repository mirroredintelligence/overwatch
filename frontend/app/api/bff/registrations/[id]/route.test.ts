// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Session } from '@/lib/auth/session';
import { readRegistration } from '@/lib/register/backend';
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
  readRegistration: vi.fn(),
}));

// The registration read the applicant's pages use (W54). The BFF passes on the registration's
// status, the invitation's values and the saved steps, and nothing else the back end holds.

const ID = 'REG-SAMPLE-1';
const read = vi.mocked(readRegistration);
const url = `https://tenant-a.example.test/api/bff/registrations/${ID}`;
const ctx = (id: string) => ({ params: Promise.resolve({ id }) });

async function sessionFor(role: Session['role']): Promise<string> {
  return sealSession({
    role,
    tenantId: TENANTS.A.id,
    host: TENANTS.A.host,
    services: [],
    sub: 'person-sample-1',
    backendToken: 'backend-token-sample-value',
    expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
  });
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  cookiesMock.mockClear();
  read.mockReset();
  read.mockResolvedValue({
    id: ID,
    status: 'draft',
    invitation: { serviceName: 'UCR West', organisationName: 'Sample Community Trust', odsCode: 'RSA01' },
    steps: { organisation: { orgType: 'nhs-trust', contactName: 'Sample Person' } },
  });
});

describe('GET /api/bff/registrations/[id]', () => {
  it('answers a reporter with the status, the invitation and the saved steps, and no back-end token', async () => {
    const cookie = await sessionFor('reporter');
    const response = await GET(requestWithCookies(url, { [SESSION_COOKIE]: cookie }), ctx(ID));
    expect(response.status).toBe(200);
    expect(response.headers.get('Cache-Control')).toBe('private, no-store');
    const body = (await response.json()) as Record<string, unknown>;
    expect(body).toEqual({
      id: ID,
      status: 'draft',
      invitation: { serviceName: 'UCR West', organisationName: 'Sample Community Trust', odsCode: 'RSA01' },
      steps: { organisation: { orgType: 'nhs-trust', contactName: 'Sample Person' } },
    });
    expect(JSON.stringify(body)).not.toContain('backend-token');
    expect(read).toHaveBeenCalledWith('backend-token-sample-value', ID);
  });

  it('drops anything the back end sends beyond the fields the page may read', async () => {
    read.mockResolvedValueOnce({
      id: ID,
      status: 'draft',
      invitation: { serviceName: 'UCR West', organisationName: 'Sample Community Trust', odsCode: 'RSA01', tenantId: 'tenant-b' },
      steps: {},
      tenantId: 'tenant-b',
      patientName: 'Not a field',
    } as never);
    const cookie = await sessionFor('reporter');
    const body = (await (await GET(requestWithCookies(url, { [SESSION_COOKIE]: cookie }), ctx(ID))).json()) as Record<string, unknown>;
    expect(Object.keys(body).sort()).toEqual(['id', 'invitation', 'status', 'steps']);
    expect(JSON.stringify(body)).not.toContain('tenant-b');
    expect(JSON.stringify(body)).not.toContain('patientName');
  });

  it('refuses a request with no session (401) and one from another role (403), without reading the back end', async () => {
    const none = await GET(requestWithCookies(url, {}), ctx(ID));
    expect(none.status).toBe(401);
    const advisor = await GET(requestWithCookies(url, { [SESSION_COOKIE]: await sessionFor('advisor') }), ctx(ID));
    expect(advisor.status).toBe(403);
    expect(read).not.toHaveBeenCalled();
  });

  it('answers 404 for an id that cannot be a registration, without reading the back end', async () => {
    const cookie = await sessionFor('reporter');
    const response = await GET(requestWithCookies(url, { [SESSION_COOKIE]: cookie }), ctx('../x'));
    expect(response.status).toBe(404);
    expect(read).not.toHaveBeenCalled();
  });

  it('answers 503 with the code not-built while the back end has no registration read', async () => {
    read.mockRejectedValueOnce(
      new FhirError(503, { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'not-built', diagnostics: 'x' }] }),
    );
    const cookie = await sessionFor('reporter');
    const response = await GET(requestWithCookies(url, { [SESSION_COOKIE]: cookie }), ctx(ID));
    expect(response.status).toBe(503);
    expect(await response.json()).toMatchObject({ code: 'not-built' });
  });

  it('gives the fixed-site answer of the location step, and none of the other location answers', async () => {
    read.mockResolvedValueOnce({
      id: ID,
      status: 'draft',
      invitation: { serviceName: 'UCR West', organisationName: 'Sample Community Trust', odsCode: 'RSA01' },
      steps: { location: { fixedSite: false, postcode: 'DT4 8XX', siteName: 'Sample Ward' } },
    });
    const cookie = await sessionFor('reporter');
    const body = (await (await GET(requestWithCookies(url, { [SESSION_COOKIE]: cookie }), ctx(ID))).json()) as { steps: object };
    expect(body.steps).toEqual({ location: { fixedSite: false } });
  });
});
