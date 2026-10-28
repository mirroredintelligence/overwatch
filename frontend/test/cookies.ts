import { vi } from 'vitest';

// A stand-in for the `next/headers` cookie store. It records every write so
// tests can check the attributes. Call `mockNextCookies()` at the top of a
// test file (vi.mock is hoisted there, see the callers).

export type CookieWrite = {
  name: string;
  value: string;
  options: Record<string, unknown>;
};

export const cookieWrites: CookieWrite[] = [];

export const fakeCookieStore = {
  set(name: string, value: string, options: Record<string, unknown> = {}) {
    cookieWrites.push({ name, value, options });
  },
  // No cookie by default; tests that need one spy on this.
  get: (_name: string): { name: string; value: string } | undefined => undefined,
};

export function resetCookieWrites() {
  cookieWrites.length = 0;
}

export function lastWrite(name: string): CookieWrite | undefined {
  return [...cookieWrites].reverse().find((w) => w.name === name);
}

export const cookiesMock = vi.fn(async () => fakeCookieStore);

export function requestWithCookies(
  url: string,
  cookies: Record<string, string>,
  init: RequestInit = {},
): Request {
  const header = Object.entries(cookies)
    .map(([k, v]) => `${k}=${v}`)
    .join('; ');
  const headers = new Headers(init.headers);
  if (header) headers.set('Cookie', header);
  return new Request(url, { ...init, headers });
}

// 32 bytes, base64. Test value only.
export const TEST_SESSION_SECRET = Buffer.alloc(32, 7).toString('base64');
