import { type Session } from '@/lib/auth/session';
import { A, DEVICE, iso, PERSON, PIN_SESSION, reporterToken } from '@/test/fixtures/reporter';
import { requestAs } from '@/test/requests';

// Helpers for the reporter's session BFF route tests (W8E): a signed-in reporter of tenant A, with the
// token the back end gave, calls a route. The token is good for half an hour, so no renewal happens.

export const REPORTER_TOKEN = reporterToken();

export const reporterSession = (over: Partial<Session> = {}): Partial<Session> => ({
  sub: PERSON,
  device: DEVICE,
  services: ['s1'],
  backendToken: REPORTER_TOKEN,
  pinSession: PIN_SESSION,
  tokenExpiresAt: iso(new Date(Date.now() + 25 * 60_000)),
  ...over,
});

export type ReporterCallOptions = {
  method?: string;
  path?: string;
  body?: unknown;
  headers?: Record<string, string>;
  csrf?: boolean;
  role?: 'reporter' | 'lead' | 'advisor' | 'exec';
  session?: Partial<Session>;
  params?: Record<string, string>;
};

/** Calls a route handler as a signed-in reporter of tenant A (a write carries its CSRF token unless `csrf: false`). */
export async function asReporter(
  route: (request: Request, context: never) => Promise<Response> | Response,
  options: ReporterCallOptions = {},
): Promise<Response> {
  const method = options.method ?? 'GET';
  const request = await requestAs(A, options.role ?? 'reporter', {
    method,
    path: options.path ?? '/api/bff/reporter/x',
    headers: { 'Content-Type': 'application/json', ...options.headers },
    body: options.body === undefined ? undefined : typeof options.body === 'string' ? options.body : JSON.stringify(options.body),
    csrf: method === 'GET' ? undefined : options.csrf === false ? undefined : true,
    session: reporterSession(options.session),
  });
  return route(request, { params: Promise.resolve(options.params ?? {}) } as never);
}

export const KEY = 'key-0123456789abcdef';
