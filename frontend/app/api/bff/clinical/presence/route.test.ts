// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Role } from '@/lib/auth/session';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { clinicalBackendHandlers, resetClinicalBackend, seenClinical } from '@/test/msw/handlers/clinical';
import { EXEC_BACKEND, execBackendHandlers } from '@/test/msw/handlers/exec';
import { requestAs } from '@/test/requests';
import { server } from '@/test/msw/server';
import { TENANTS } from '@/test/tenants';
import { GET, PUT } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});


beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', EXEC_BACKEND);
  vi.stubEnv('NODE_ENV', 'production');
  resetClinicalBackend();
  server.use(...clinicalBackendHandlers, ...execBackendHandlers);
});

afterEach(() => vi.unstubAllEnvs());

const put = async (body: unknown, role: Role = 'clinical') =>
  PUT(await requestAs(TENANTS.A, role, { method: 'PUT', path: '/api/bff/clinical/presence', csrf: true, body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' } }));

describe('/api/bff/clinical/presence', () => {
  it('reads the clinician\'s own presence and the count of advisors available, from the back end\'s root path', async () => {
    const response = await GET(await requestAs(TENANTS.A, 'clinical', { path: '/api/bff/clinical/presence' }));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ presence: 'busy', available: 2 });
    expect(seenClinical.at(-1)?.path).toBe('/clinical/presence');
  });

  it('saves a presence and answers it', async () => {
    const response = await put({ presence: 'away' });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ presence: 'away' });
    expect(seenClinical.at(-1)).toMatchObject({ method: 'PUT', path: '/clinical/presence', body: { presence: 'away' } });
  });

  it('refuses a presence the back end does not take, with no call', async () => {
    resetClinicalBackend();
    expect((await put({ presence: 'lunch' })).status).toBe(400);
    expect(seenClinical).toHaveLength(0);
  });

  it('refuses a role that is not a clinical advisor', async () => {
    expect((await GET(await requestAs(TENANTS.A, 'advisor', { path: '/api/bff/clinical/presence' }))).status).toBe(403);
  });
});
