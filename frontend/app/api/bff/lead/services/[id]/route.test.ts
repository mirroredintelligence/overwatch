// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { GET } from './route';

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

const ROOT = BACKEND_BASE.replace(/\/fhir$/, '');
const URL_ = 'https://app.test/api/bff/lead/services/s-ucr-east';
const ctx = { params: Promise.resolve({ id: 's-ucr-east' }) };

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
  server.use(
    http.get(`${BACKEND_BASE}/HealthcareService/s-ucr-east`, () => HttpResponse.json({ resourceType: 'HealthcareService', id: 's-ucr-east', name: 'UCR East' })),
  );
});

afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/lead/services/[id]', () => {
  it('answers 403 to an advisor', async () => {
    expect((await GET(await leadRequest(URL_, 'advisor'), ctx)).status).toBe(403);
  });

  it('answers the name, the suspension, when, how many requests expired and the register number', async () => {
    server.use(
      http.get(`${ROOT}/lead/services/s-ucr-east/suspension`, () =>
        HttpResponse.json({ suspended: true, since: '2026-10-30T14:20:00Z', reason: 'closed-unexpectedly', expiredRequests: 2, registerNumber: '07700900123' }),
      ),
    );
    const response = await GET(await leadRequest(URL_, 'lead'), ctx);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      name: 'UCR East',
      suspended: true,
      since: '2026-10-30T14:20:00Z',
      expiredRequests: 2,
      registerPhone: '07700900123',
    });
  });

  it('answers not suspended with no since, no count, and the register number when there is one', async () => {
    server.use(
      http.get(`${ROOT}/lead/services/s-ucr-east/suspension`, () =>
        HttpResponse.json({ suspended: false, since: null, reason: null, expiredRequests: null, registerNumber: null }),
      ),
    );
    const response = await GET(await leadRequest(URL_, 'lead'), ctx);
    expect(await response.json()).toEqual({ name: 'UCR East', suspended: false, registerPhone: null });
  });

  it('answers 503 when the suspension cannot be read, and never a suspension it does not know', async () => {
    server.use(http.get(`${ROOT}/lead/services/s-ucr-east/suspension`, () => HttpResponse.json({}, { status: 503 })));
    const response = await GET(await leadRequest(URL_, 'lead'), ctx);
    expect(response.status).toBe(503);
  });
});
