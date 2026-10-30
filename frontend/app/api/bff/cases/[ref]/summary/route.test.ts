// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { GET } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

const SR_URL = `${BACKEND_BASE}/ServiceRequest/4821`;

function session(role: Role): Session {
  return {
    role,
    services: [],
    sub: 'advisor-1',
    backendToken: 'token-for-advisor',
    expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
  };
}

async function get(role: Role | null): Promise<Response> {
  const cookies: Record<string, string> = {};
  if (role !== null) cookies[SESSION_COOKIE] = await sealSession(session(role));
  return GET(requestWithCookies('https://app.test/api/bff/cases/4821/summary', cookies), {
    params: Promise.resolve({ ref: '4821' }),
  });
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
  server.use(
    http.get(SR_URL, () =>
      HttpResponse.json(
        {
          resourceType: 'ServiceRequest',
          id: '4821',
          contained: [
            {
              resourceType: 'Patient',
              id: 'p',
              address: [{ postalCode: 'DT4 8XX' }],
              extension: [{ url: 'https://diucs.example/StructureDefinition/age-band', valueCode: '80+' }],
            },
          ],
          extension: [{ url: 'https://diucs.example/StructureDefinition/referrer-type', valueCode: 'gp' }],
          priority: 'routine',
          reasonCode: [{ coding: [{ system: 'https://diucs.example/CodeSystem/need-category', code: 'frailty' }] }],
        },
        { headers: { ETag: 'W/"1"' } },
      ),
    ),
  );
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('GET /api/bff/cases/[ref]/summary (W15)', () => {
  it('answers the display strings, and says what the back end does not yet send as not recorded', async () => {
    const response = await get('advisor');

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      reference: '4821',
      referrer: 'GP',
      ageBand: '80+',
      postcode: 'DT4 8XX',
      needs: 'Frailty',
      urgency: 'Today',
      scores: 'None given',
      destination: 'Not recorded in this view',
      booked: 'Not recorded in this view',
      dataAge: 'Not recorded in this view',
    });
  });

  it('answers 403 for a reporter and reads nothing', async () => {
    expect((await get('reporter')).status).toBe(403);
  });

  it('is never cached', async () => {
    expect((await get('advisor')).headers.get('cache-control')).toBe('no-store');
  });
});
