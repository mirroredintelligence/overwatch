// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Session } from '@/lib/auth/session';
import { readAddresses } from '@/lib/register/backend';
import { FhirError } from '@/lib/fhir/client';
import { cookiesMock, requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { GET } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});
vi.mock('@/lib/register/backend', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/register/backend')>()),
  readAddresses: vi.fn(),
}));

// The postcode lookup for a fixed site (W24). The reporter's session is needed; the postcode is
// normalised before the back end sees it, and only the id and the label of each address go back.

const lookup = vi.mocked(readAddresses);
const url = (query: string) => `https://tenant-a.example.test/api/bff/addresses${query}`;

async function sessionFor(role: Session['role']): Promise<string> {
  return sealSession({
    role,
    services: [],
    sub: 'person-sample-1',
    backendToken: 'backend-token-sample-value',
    expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
  });
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  cookiesMock.mockClear();
  lookup.mockReset();
  lookup.mockResolvedValue([
    { id: 'addr-1', label: 'Sample House, Dorchester, DT4 8XX', uprn: '123' } as never,
    { id: 'addr-2', label: 'Sample Flat, Dorchester, DT4 8XX' },
  ]);
});

describe('GET /api/bff/addresses', () => {
  it('looks up the normalised postcode with the reporter’s token and returns the id and label of each address', async () => {
    const response = await GET(requestWithCookies(url('?postcode=dt4%208xx'), { [SESSION_COOKIE]: await sessionFor('reporter') }));
    expect(response.status).toBe(200);
    expect(response.headers.get('Cache-Control')).toBe('no-store');
    expect(lookup).toHaveBeenCalledWith('backend-token-sample-value', 'DT4 8XX');
    expect(await response.json()).toEqual([
      { id: 'addr-1', label: 'Sample House, Dorchester, DT4 8XX' },
      { id: 'addr-2', label: 'Sample Flat, Dorchester, DT4 8XX' },
    ]);
  });

  it('answers 400 for a postcode that is not one, without a lookup', async () => {
    const cookie = await sessionFor('reporter');
    for (const query of ['', '?postcode=DT4', '?postcode=12345', '?postcode=DT4%208XX&postcode=SW1A%201AA']) {
      const response = await GET(requestWithCookies(url(query), { [SESSION_COOKIE]: cookie }));
      expect(response.status).toBe(400);
    }
    expect(lookup).not.toHaveBeenCalled();
  });

  it('refuses no session (401) and another role (403)', async () => {
    expect((await GET(requestWithCookies(url('?postcode=DT4%208XX'), {}))).status).toBe(401);
    expect((await GET(requestWithCookies(url('?postcode=DT4%208XX'), { [SESSION_COOKIE]: await sessionFor('advisor') }))).status).toBe(403);
    expect(lookup).not.toHaveBeenCalled();
  });

  it('answers 503 not-built while the back end has no address lookup', async () => {
    lookup.mockRejectedValueOnce(new FhirError(503, { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'not-built', diagnostics: 'x' }] }));
    const response = await GET(requestWithCookies(url('?postcode=DT4%208XX'), { [SESSION_COOKIE]: await sessionFor('reporter') }));
    expect(response.status).toBe(503);
    expect(await response.json()).toMatchObject({ code: 'not-built' });
  });
});
