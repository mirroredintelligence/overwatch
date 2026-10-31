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
  return GET(await requestAs(TENANTS.A, role, { path: `/api/bff/clinical/requests/${id}/seen` }), { params: Promise.resolve({ id }) });
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', EXEC_BACKEND);
  vi.stubEnv('NODE_ENV', 'production');
  resetClinicalBackend();
  server.use(...clinicalBackendHandlers, ...execBackendHandlers);
});

afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/clinical/requests/[id]/seen', () => {
  it('reads what the advisor saw from the back end’s root and answers the display as it is', async () => {
    const response = await get('req-5001');
    expect(response.status).toBe(200);
    const body = (await response.json()) as { seen: { state: string; shownAt: string; lines: { service: string; figure: string | null }[] } };
    expect(body.seen.state).toBe('shown');
    expect(body.seen.shownAt).toBe('2026-10-23T13:13:20Z');
    expect(body.seen.lines.map((line) => [line.service, line.figure])).toEqual([
      ['UCR West', '4'],
      ['Hospital at home', '+2'],
      ['Ward B', '5'],
      ['UCR East', null],
    ]);
    expect(seenClinical.map((call) => call.path)).toEqual(['/clinical/requests/req-5001/seen']);
  });

  it('answers no display kept and a display that cannot be read as they are, never as an empty display', async () => {
    expect(((await (await get('req-5007')).json()) as { seen: { state: string } }).seen.state).toBe('none');
    expect(((await (await get('req-5008')).json()) as { seen: { state: string } }).seen.state).toBe('unreadable');
  });

  it('is the one 404 for a request the clinician does not hold, an id that is nowhere and an id that is not shaped like one', async () => {
    const refused = await get('req-0000');
    expect(refused.status).toBe(404);
    expect(await refused.json()).toEqual({ code: 'not-found', message: 'We could not find that.' });
    const shaped = await get('..%2Fetc');
    expect(shaped.status).toBe(404);
    expect(seenClinical.map((call) => call.path)).toEqual(['/clinical/requests/req-0000/seen']);
  });

  it('says the back end is unavailable when it fails, and never an empty display', async () => {
    const response = await get('req-fail');
    expect(response.status).toBeGreaterThanOrEqual(500);
    expect(JSON.stringify(await response.json())).not.toMatch(/lines|shown/);
  });

  it('refuses every role but a clinical advisor, with no back-end call', async () => {
    for (const role of ['advisor', 'lead', 'exec', 'reporter', 'owner'] as Role[]) {
      expect((await get('req-5001', role)).status, role).toBe(403);
    }
    expect(seenClinical).toEqual([]);
  });

  it('never carries a postcode, a district, an identifier or a number', async () => {
    expect(JSON.stringify(await (await get('req-5001')).json())).not.toMatch(/postcode|district|practitioner|svc-|0[0-9]{4} ?[0-9]{6}/i);
  });
});
