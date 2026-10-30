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

async function get(role: Role, query: string) {
  return GET(await requestAs(TENANTS.A, role, { path: `/api/bff/clinical/requests${query}` }));
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', EXEC_BACKEND);
  vi.stubEnv('NODE_ENV', 'production');
  resetClinicalBackend();
  server.use(...clinicalBackendHandlers, ...execBackendHandlers);
});

afterEach(() => vi.unstubAllEnvs());

type Item = { id: string; status: string; glance: { caseReference: string; ageBand: string; news2: number } | null; returnsAt: string | null };

describe('GET /api/bff/clinical/requests', () => {
  it('lists the waiting requests with the case glance, and no patient detail', async () => {
    const response = await get('clinical', '?tab=waiting');
    expect(response.status).toBe(200);
    const body = (await response.json()) as { items: Item[] };
    expect(body.items.map((item) => item.id)).toEqual(['req-4821', 'req-4822']);
    expect(body.items[0]?.glance).toMatchObject({ caseReference: '4821', ageBand: '80+', news2: 2 });
    expect(JSON.stringify(body)).not.toMatch(/practitioner|phone|postcode/i);
    expect(seenClinical.at(-1)?.path).toBe('/Task?code=clinical-advice&status=requested');
  });

  it('lists Mine from the in-progress status, with when each returns to the queue', async () => {
    const response = await get('clinical', '?tab=mine');
    expect(response.status).toBe(200);
    const body = (await response.json()) as { items: Item[] };
    expect(body.items.map((item) => item.id)).toEqual(['req-5001']);
    expect(body.items[0]?.returnsAt).toBe('2026-10-23T13:29:30Z');
    expect(seenClinical.at(-1)?.path).toBe('/Task?code=clinical-advice&status=in-progress');
  });

  it('lists Done from the completed status, with the advice given', async () => {
    const response = await get('clinical', '?tab=done');
    expect(response.status).toBe(200);
    const body = (await response.json()) as { items: { id: string; advice: { choice: string } }[] };
    expect(body.items.map((item) => [item.id, item.advice.choice])).toEqual([['req-5002', 'use-another-service']]);
    expect(seenClinical.at(-1)?.path).toBe('/Task?code=clinical-advice&status=completed');
  });

  it('refuses a tab it does not know, with no back-end call', async () => {
    resetClinicalBackend();
    expect((await get('clinical', '?tab=everything')).status).toBe(400);
    expect(seenClinical).toHaveLength(0);
  });

  it('refuses a role that is not a clinical advisor', async () => {
    expect((await get('advisor', '?tab=waiting')).status).toBe(403);
  });
});
