// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Role } from '@/lib/auth/session';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { clinicalBackendHandlers, resetClinicalBackend } from '@/test/msw/handlers/clinical';
import { EXEC_BACKEND, execBackendHandlers } from '@/test/msw/handlers/exec';
import { requestAs } from '@/test/requests';
import { server } from '@/test/msw/server';
import { TENANTS } from '@/test/tenants';
import { GET } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

async function get(id: string, role: Role = 'clinical') {
  return GET(await requestAs(TENANTS.A, role, { path: `/api/bff/clinical/requests/${id}` }), { params: Promise.resolve({ id }) });
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', EXEC_BACKEND);
  vi.stubEnv('NODE_ENV', 'production');
  resetClinicalBackend();
  server.use(...clinicalBackendHandlers, ...execBackendHandlers);
});

afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/clinical/requests/[id]', () => {
  it('reads one request: the case glance, the reason and when a held request returns to the queue', async () => {
    const response = await get('req-5001');
    expect(response.status).toBe(200);
    const body = (await response.json()) as { request: { id: string; status: string; glance: { caseReference: string; needs: string[] }; returnsAt: string } };
    expect(body.request).toMatchObject({ id: 'req-5001', status: 'in-progress', returnsAt: '2026-10-23T13:29:30Z' });
    expect(body.request.glance).toMatchObject({ caseReference: '5001', needs: ['frailty', 'fall-no-injury'] });
  });

  it('answers a request whose case could not be read with no glance, so the screen can say so', async () => {
    const body = (await (await get('req-5003')).json()) as { request: { glance: unknown } };
    expect(body.request.glance).toBeNull();
  });

  it('is the same 404 for an id that is nowhere and one the back end refuses, and never says which', async () => {
    const response = await get('req-0000');
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ code: 'not-found', message: 'We could not find that.' });
  });

  it('refuses an id that is not shaped like one, with no back-end call', async () => {
    expect((await get('..%2Fetc')).status).toBe(404);
  });

  it('refuses a role that is not a clinical advisor', async () => {
    expect((await get('req-5001', 'advisor')).status).toBe(403);
  });

  it('never carries a postcode, a district or a practitioner', async () => {
    expect(JSON.stringify(await (await get('req-5001')).json())).not.toMatch(/postcode|district|practitioner/i);
  });
});
