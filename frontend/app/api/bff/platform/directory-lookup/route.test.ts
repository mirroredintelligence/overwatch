// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { requestAsOperator } from '@/test/operator';
import { server } from '@/test/msw/server';

// The route is operator-only and answers a suggestion. It saves nothing, and a value that is not a domain name is
// refused before any call goes out.

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('NODE_ENV', 'production');
});

const ID = 'c5901e0b-8d43-4ae8-97c3-ca6c52573a33';

describe('GET /platform/directory-lookup', () => {
  it('answers the directory id of a domain to the platform operator', async () => {
    const { GET } = await import('./route');
    server.use(http.get('https://login.microsoftonline.com/example.nhs.uk/v2.0/.well-known/openid-configuration', () =>
      HttpResponse.json({ issuer: `https://login.microsoftonline.com/${ID}/v2.0` }),
    ));
    const response = await GET(await requestAsOperator('platform-operator', { path: '/api/bff/platform/directory-lookup?domain=example.nhs.uk' }));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ domain: 'example.nhs.uk', directoryId: ID });
    expect(response.headers.get('cache-control')).toContain('no-store');
  });

  it('refuses a value that is not a domain name, and calls nothing out', async () => {
    const { GET } = await import('./route');
    let called = false;
    server.use(http.get('https://login.microsoftonline.com/*', () => {
      called = true;
      return HttpResponse.json({});
    }));
    const response = await GET(await requestAsOperator('platform-operator', { path: '/api/bff/platform/directory-lookup?domain=https%3A%2F%2Fevil.example' }));
    expect(response.status).toBe(400);
    expect(called).toBe(false);
  });

  it('refuses a support person, who may not create or bind a tenant', async () => {
    const { GET } = await import('./route');
    const response = await GET(await requestAsOperator('support', { path: '/api/bff/platform/directory-lookup?domain=example.nhs.uk' }));
    expect(response.status).toBe(403);
  });
});
