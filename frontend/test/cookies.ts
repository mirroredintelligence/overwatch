import { vi } from 'vitest';

// A stand-in for the `next/headers` cookie store and header list. It records every write so tests can
// check the attributes, and it keeps a jar so a cookie that was set can be read back with `get`
// (a write of an empty value, or with `maxAge: 0`, removes it, as a browser would). Call it from the
// test file's `vi.mock('next/headers', ...)` (hoisted there, see the callers):
//
//   vi.mock('next/headers', async () => {
//     const m = await import('@/test/cookies');
//     return { cookies: m.cookiesMock, headers: m.headersMock };
//   });
//
// This file imports nothing from the application, because the mock factory loads it while
// `next/headers` is being replaced. `test/requests.ts` has the helpers that seal a session.

export type CookieWrite = {
  name: string;
  value: string;
  options: Record<string, unknown>;
};

export const cookieWrites: CookieWrite[] = [];

/** The cookies the fake store holds now. Seed it with `seedCookies`. */
export const cookieJar = new Map<string, string>();

export const fakeCookieStore = {
  set(name: string, value: string, options: Record<string, unknown> = {}) {
    cookieWrites.push({ name, value, options });
    if (value === '' || options.maxAge === 0) cookieJar.delete(name);
    else cookieJar.set(name, value);
  },
  get(name: string): { name: string; value: string } | undefined {
    const value = cookieJar.get(name);
    return value === undefined ? undefined : { name, value };
  },
  has(name: string): boolean {
    return cookieJar.has(name);
  },
  delete(name: string) {
    cookieWrites.push({ name, value: '', options: { maxAge: 0 } });
    cookieJar.delete(name);
  },
};

export function seedCookies(cookies: Record<string, string>) {
  for (const [name, value] of Object.entries(cookies)) cookieJar.set(name, value);
}

/** Forgets the writes and the jar. Call it in `beforeEach`. */
export function resetCookieWrites() {
  cookieWrites.length = 0;
  cookieJar.clear();
  requestHost = DEFAULT_HOST;
}

export function lastWrite(name: string): CookieWrite | undefined {
  return [...cookieWrites].reverse().find((w) => w.name === name);
}

export const cookiesMock = vi.fn(async () => fakeCookieStore);

// The host the request in progress was addressed to, as `headers()` shows it to a Server Component.
const DEFAULT_HOST = 'tenant-a.example.test';
let requestHost = DEFAULT_HOST;

/** Sets the host `headers()` reports until the next `resetCookieWrites`. */
export function setRequestHost(host: string) {
  requestHost = host;
}

export const headersMock = vi.fn(async () => new Headers({ host: requestHost }));

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
