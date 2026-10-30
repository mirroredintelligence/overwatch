import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { BACKEND_ROOT } from '@/test/fixtures/links';
import { server } from '@/test/msw/server';

// The applicant's back-end stand-in (W23 to W27, W7B A2 and A1). Each test answers the routes it
// calls with the real shapes of routes_registration_session.py and routes_registration_views.py and
// reads back what was sent. Sample values only: no real number, code, token or patient.

export type Seen = { method: string; path: string; host: string | null; body: unknown; auth: string | null; idem: string | null };

/** Every call the BFF made to the back end in this test, newest last. */
export const seen: Seen[] = [];

export function resetSeen(): void {
  seen.length = 0;
}

/** A token shaped like one the back end signed: its subject and expiry are read, never its signature. */
export function unsignedToken(sub: string, expSeconds: number): string {
  const encode = (value: unknown) => Buffer.from(JSON.stringify(value)).toString('base64url');
  return `${encode({ alg: 'HS256', typ: 'JWT' })}.${encode({ sub, exp: expSeconds, role: 'reporter' })}.c2lnbmF0dXJl`;
}

type Method = 'get' | 'post' | 'put';

/** Answers one back-end path once, and records the call. A path with no answer set is a test fault. */
export function answerBackend(method: Method, path: string, status: number, body: unknown, headers: Record<string, string> = {}): void {
  const resolver = (async ({ request }: { request: Request }) => {
    const text = await request.text();
    seen.push({
      method: method.toUpperCase(),
      path: new URL(request.url).pathname,
      host: request.headers.get('host'),
      body: text === '' ? null : (JSON.parse(text) as unknown),
      auth: request.headers.get('authorization'),
      idem: request.headers.get('idempotency-key'),
    });
    return HttpResponse.json(body as Record<string, unknown>, { status, headers: { 'Cache-Control': 'no-store', ...headers } });
  }) as HttpResponseResolver;
  server.use(http[method](`${BACKEND_ROOT}${path}`, resolver));
}

/** Answers a back-end path with a network failure, for the 503 path. */
export function breakBackend(method: Method, path: string): void {
  server.use(http[method](`${BACKEND_ROOT}${path}`, (() => HttpResponse.error()) as HttpResponseResolver));
}
