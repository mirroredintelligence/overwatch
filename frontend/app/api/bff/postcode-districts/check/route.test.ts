// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { BACKEND_ROOT } from '@/test/msw/handlers/lead';
import { server } from '@/test/msw/server';
import { GET } from './route';

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

// The district check (DEC-1329), lead only: the back end's count is passed on when it reads as a count, and an
// answer that does not is an error, never a guessed count.

const URL_ = 'https://app.test/api/bff/postcode-districts/check';

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('OVERWATCH_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/postcode-districts/check', () => {
  it('passes on the back end count for the district typed', async () => {
    let asked: string | null = null;
    server.use(
      http.get(`${BACKEND_ROOT}/postcode-districts/check`, ({ request }) => {
        asked = new URL(request.url).searchParams.get('text');
        return HttpResponse.json({ prefix: 'DT4', postcodes: 1505 });
      }),
    );
    const response = await GET(await leadRequest(`${URL_}?text=dt4`, 'lead'));
    expect(response.status).toBe(200);
    expect(asked).toBe('dt4');
    expect(await response.json()).toEqual({ prefix: 'DT4', postcodes: 1505 });
  });

  it('answers an error, not a count, when the back end answer is not a count', async () => {
    server.use(
      http.get(`${BACKEND_ROOT}/postcode-districts/check`, () => HttpResponse.json({ prefix: 'DT4', postcodes: 1.5 })),
    );
    const response = await GET(await leadRequest(`${URL_}?text=DT4`, 'lead'));
    expect(response.status).toBe(400);
    expect(await response.text()).not.toMatch(/postcodes/);
  });

  it('refuses a request with no district text, without calling the back end', async () => {
    let called = false;
    server.use(
      http.get(`${BACKEND_ROOT}/postcode-districts/check`, () => {
        called = true;
        return HttpResponse.json({});
      }),
    );
    const response = await GET(await leadRequest(URL_, 'lead'));
    expect(response.status).toBe(400);
    expect(called).toBe(false);
  });

  it('is the non-revealing refusal for a role that is not the lead', async () => {
    const response = await GET(await leadRequest(`${URL_}?text=DT4`, 'reporter'));
    expect(response.status).toBe(403);
  });
});
