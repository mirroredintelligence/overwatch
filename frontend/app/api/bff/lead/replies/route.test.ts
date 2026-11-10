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
const URL_ = 'https://app.test/api/bff/lead/replies';

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('OVERWATCH_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/lead/replies', () => {
  it('answers 403 to an advisor', async () => {
    expect((await GET(await leadRequest(URL_, 'advisor'))).status).toBe(403);
  });

  it('passes the waiting replies on with the problem in words, and nothing about a phone', async () => {
    server.use(
      http.get(`${ROOT}/admin/failed-replies`, () =>
        HttpResponse.json({
          replies: [
            { sid: 'SM1', receivedAt: '2026-11-10T10:01:08Z', step: 'enqueue', text: 'Y', senderName: 'Dee Manager' },
            { sid: 'SM2', receivedAt: '2026-11-10T09:00:00Z', step: 'find-sender', text: '3', senderName: null, phoneHash: 'x'.repeat(64) },
            { receivedAt: 'no id', step: 'enqueue' },
          ],
        }),
      ),
    );
    const response = await GET(await leadRequest(URL_, 'lead'));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      items: [
        { sid: 'SM1', receivedAt: '2026-11-10T10:01:08Z', text: 'Y', senderName: 'Dee Manager', problem: 'We could not queue it.' },
        { sid: 'SM2', receivedAt: '2026-11-10T09:00:00Z', text: '3', senderName: null, problem: 'We could not look up the sender.' },
      ],
    });
  });

  it('is an error, not an empty list, when the back end answers in another shape', async () => {
    server.use(http.get(`${ROOT}/admin/failed-replies`, () => HttpResponse.json({ nothing: true })));
    expect((await GET(await leadRequest(URL_, 'lead'))).status).toBeGreaterThanOrEqual(500);
  });
});
