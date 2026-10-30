// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { POST } from './route';

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

const URL_ = 'https://app.test/api/bff/lead/services/s-ucr-east/move';
const ctx = { params: Promise.resolve({ id: 's-ucr-east' }) };
const KEY = 'move-key-0001';

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/lead/services/[id]/move', () => {
  it('answers 400 for a phone that is not a UK mobile, and for a date that is not a date', async () => {
    const bad = [
      { toPhone: '0123', until: 'changed' },
      { toPhone: '07700 900123', until: 'date', date: '2026-02-30' },
      { toPhone: '07700 900123', until: 'date' },
      { toPhone: '07700 900123', until: 'forever' },
    ];
    for (const body of bad) {
      const response = await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY, body }), ctx);
      expect(response.status).toBe(400);
    }
  });

  it('sends until changed as $move with no until part, and answers the move id only', async () => {
    let sent: unknown;
    server.use(
      http.post(`${BACKEND_BASE}/HealthcareService/s-ucr-east/$move`, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json({ resourceType: 'Parameters', parameter: [{ name: 'moveId', valueString: 'move-1' }] }, { status: 201 });
      }),
    );
    const response = await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY, body: { toPhone: '07700 900123', until: 'changed' } }), ctx);
    expect(response.status).toBe(201);
    expect(await response.json()).toEqual({ moveId: 'move-1' });
    expect(sent).toEqual({ resourceType: 'Parameters', parameter: [{ name: 'toMobile', valueString: '07700 900123' }] });
  });

  it('sends a cover until a date as the end of that day in London, with its offset', async () => {
    let sent: { parameter: { name: string; valueDateTime?: string }[] } | undefined;
    server.use(
      http.post(`${BACKEND_BASE}/HealthcareService/s-ucr-east/$move`, async ({ request }) => {
        sent = (await request.json()) as typeof sent;
        return HttpResponse.json({ resourceType: 'Parameters', parameter: [{ name: 'moveId', valueString: 'move-2' }] }, { status: 201 });
      }),
    );
    await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY, body: { toPhone: '07700 900123', until: 'date', date: '2026-06-01' } }), ctx);
    expect(sent?.parameter.find((p) => p.name === 'until')).toEqual({ name: 'until', valueDateTime: '2026-06-01T23:59:59+01:00' });
  });

  it('answers 403 to an advisor', async () => {
    expect((await POST(await leadRequest(URL_, 'advisor', { method: 'POST', csrf: true, key: KEY, body: { toPhone: '07700 900123', until: 'changed' } }), ctx)).status).toBe(403);
  });
});
