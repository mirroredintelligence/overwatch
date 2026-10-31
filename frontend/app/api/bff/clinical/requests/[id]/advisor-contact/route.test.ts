// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Role } from '@/lib/auth/session';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { clinicalBackendHandlers, resetClinicalBackend, seenClinical } from '@/test/msw/handlers/clinical';
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
  return GET(await requestAs(TENANTS.A, role, { path: `/api/bff/clinical/requests/${id}/advisor-contact` }), { params: Promise.resolve({ id }) });
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', EXEC_BACKEND);
  vi.stubEnv('NODE_ENV', 'production');
  resetClinicalBackend();
  server.use(...clinicalBackendHandlers, ...execBackendHandlers);
});

afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/clinical/requests/[id]/advisor-contact', () => {
  it('answers the advisor’s work phone whole with their name, from the back end’s root, and is never stored', async () => {
    const response = await get('req-5001');
    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toContain('no-store');
    expect(await response.json()).toEqual({ contact: { via: 'work-phone', phone: '07700 900123', name: 'Sample Advisor' } });
    expect(seenClinical.map((call) => call.path)).toEqual(['/clinical/requests/req-5001/advisor-contact']);
  });

  it('answers the advisor line with no name, and no number as none', async () => {
    expect(await (await get('req-5006')).json()).toEqual({ contact: { via: 'advisor-line', phone: '01305 900000', name: null } });
    expect(await (await get('req-5007')).json()).toEqual({ contact: { via: null, phone: null, name: null } });
  });

  it('is the one 404 for a request the clinician does not hold or one that is nowhere, and carries no number', async () => {
    const response = await get('req-0000');
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ code: 'not-found', message: 'We could not find that.' });
    expect((await get('..%2Fetc')).status).toBe(404);
  });

  it('says the back end is unavailable when it fails', async () => {
    expect((await get('req-fail')).status).toBeGreaterThanOrEqual(500);
  });

  it('refuses every role but a clinical advisor, with no back-end call', async () => {
    for (const role of ['advisor', 'lead', 'exec', 'reporter', 'owner'] as Role[]) {
      expect((await get('req-5001', role)).status, role).toBe(403);
    }
    expect(seenClinical).toEqual([]);
  });

  it('logs nothing: no console call is made, whatever the back end answers', async () => {
    const spies = (['log', 'info', 'warn', 'error', 'debug'] as const).map((name) => vi.spyOn(console, name).mockImplementation(() => undefined));
    await get('req-5001');
    await get('req-0000');
    await get('req-fail');
    for (const spy of spies) expect(spy).not.toHaveBeenCalled();
  });
});
