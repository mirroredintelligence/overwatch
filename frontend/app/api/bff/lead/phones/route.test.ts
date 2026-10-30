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
const URL_ = 'https://app.test/api/bff/lead/phones';

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/lead/phones', () => {
  it('answers 403 to an advisor', async () => {
    expect((await GET(await leadRequest(URL_, 'advisor'))).status).toBe(403);
  });

  it('passes the phones on, each by its last three digits and the services it holds', async () => {
    server.use(
      http.get(`${ROOT}/lead/phones`, () =>
        HttpResponse.json({
          phones: [
            {
              phoneEnding: '777',
              role: 'Duty manager',
              services: [
                { id: 's-a', name: 'Virtual ward' },
                { id: 's-b', name: 'UCR East' },
              ],
              channel: 'text',
              lastSeen: '2026-10-30T09:21:00Z',
            },
          ],
        }),
      ),
    );
    const response = await GET(await leadRequest(URL_, 'lead'));
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body).toEqual({
      phones: [
        {
          phoneEnding: '777',
          role: 'Duty manager',
          services: [
            { id: 's-a', name: 'Virtual ward' },
            { id: 's-b', name: 'UCR East' },
          ],
          channel: 'text',
          lastSeen: '2026-10-30T09:21:00Z',
        },
      ],
    });
  });

  it('answers 503 when the phones cannot be read, and never an empty list', async () => {
    server.use(http.get(`${ROOT}/lead/phones`, () => HttpResponse.json({}, { status: 503 })));
    const response = await GET(await leadRequest(URL_, 'lead'));
    expect(response.status).toBe(503);
    expect(await response.json()).not.toHaveProperty('phones');
  });
});
