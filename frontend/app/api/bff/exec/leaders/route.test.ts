// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Role } from '@/lib/auth/session';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { EXEC_BACKEND, execBackendHandlers, resetExecBackend, seenBackend } from '@/test/msw/handlers/exec';
import { requestAs } from '@/test/requests';
import { server } from '@/test/msw/server';
import { TENANTS } from '@/test/tenants';
import { GET } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

const get = async (role: Role) => GET(await requestAs(TENANTS.A, role, { path: '/api/bff/exec/leaders' }));

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', EXEC_BACKEND);
  vi.stubEnv('NODE_ENV', 'production');
  resetExecBackend();
  server.use(...execBackendHandlers);
});

afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/exec/leaders', () => {
  it('lists the leaders a deputy can be chosen from, by id and name, from the leadership read', async () => {
    const response = await get('exec');
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      leaders: [
        { id: 'pr-0101', name: 'Sample Lead One' },
        { id: 'pr-0102', name: 'Sample Lead Two' },
      ],
    });
    expect(seenBackend[0]?.path).toBe('/Practitioner?role=leadership');
  });

  it('is open to a shift lead too, and refuses every other role', async () => {
    expect((await get('lead')).status).toBe(200);
    for (const role of ['advisor', 'clinical', 'reporter', 'owner'] as const) expect((await get(role)).status).toBe(403);
  });
});
