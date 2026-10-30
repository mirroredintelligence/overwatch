// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { TOKEN_ORG_A } from '@/test/msw/handlers/board';
import { clinicalBackendHandlers, resetClinicalBackend } from '@/test/msw/handlers/clinical';
import { EXEC_BACKEND, execBackendHandlers } from '@/test/msw/handlers/exec';
import { server } from '@/test/msw/server';
import { GET } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

async function get(role: Role, query: string) {
  const s: Session = { role, services: [], sub: 'user-1', backendToken: TOKEN_ORG_A, expiresAt: new Date(Date.now() + 3_600_000).toISOString() };
  return GET(requestWithCookies(`https://app.test/api/bff/clinical/requests${query}`, { [SESSION_COOKIE]: await sealSession(s) }));
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', EXEC_BACKEND);
  vi.stubEnv('NODE_ENV', 'production');
  resetClinicalBackend();
  server.use(...clinicalBackendHandlers, ...execBackendHandlers);
});

afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/clinical/requests', () => {
  it('lists the waiting requests as urgency, reason and case, with no patient detail', async () => {
    const response = await get('clinical', '?tab=waiting');
    expect(response.status).toBe(200);
    const body = (await response.json()) as { items: { id: string; urgency: string }[] };
    expect(body.items.map((item) => item.id)).toEqual(['req-4821', 'req-4822']);
    expect(JSON.stringify(body)).not.toMatch(/practitioner|phone|postcode/i);
  });

  it('answers unavailable for the Mine and Done tabs, which the back end does not list', async () => {
    expect((await get('clinical', '?tab=mine')).status).toBe(503);
    expect((await get('clinical', '?tab=done')).status).toBe(503);
  });

  it('refuses a tab it does not know', async () => {
    expect((await get('clinical', '?tab=everything')).status).toBe(400);
  });

  it('refuses a role that is not a clinical advisor', async () => {
    expect((await get('advisor', '?tab=waiting')).status).toBe(403);
  });
});
