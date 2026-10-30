// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cookiesMock, requestWithCookies, resetCookieWrites, TEST_SESSION_SECRET } from '@/test/cookies';
import { GET } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  resetCookieWrites();
  cookiesMock.mockClear();
});

afterEach(() => vi.unstubAllEnvs());

const call = (token: string) =>
  GET(requestWithCookies(`https://app.test/api/bff/invitations/${token}`, {}), {
    params: Promise.resolve({ token }),
  });

describe('GET /api/bff/invitations/[token]', () => {
  it('answers not-built (503) until the back end can look an invitation up, and never says it is valid', async () => {
    const response = await call('tok');
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({ code: 'not-built', message: 'This is not available yet.' });
  });

  it('refuses a token that cannot be an invitation, with the same answer as an unknown one', async () => {
    const response = await call('bad token!');
    expect(response.status).toBe(410);
    expect(response.headers.get('Cache-Control')).toBe('no-store');
  });
});
