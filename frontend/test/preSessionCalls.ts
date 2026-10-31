import { http, HttpResponse, type RequestHandler } from 'msw';
import { BACKEND, A } from '@/test/fixtures/reporter';
import { requestPreSession, type PreSessionOptions } from '@/test/requests';
import { server } from '@/test/msw/server';

// Helpers for the reporter's pre-session BFF route tests (W8E): a phone with no session calls a route,
// the stand-in back end keeps what it was sent (path, host, bearer, body) and answers what the test
// says. Sample values only.

export type SeenBackend = { method: string; path: string; host: string | null; authorization: string | null; body: unknown };
export const seenBackend: SeenBackend[] = [];
export function resetSeenBackend() {
  seenBackend.length = 0;
}

/** The back end's OperationOutcome for a refused code, with the extra field the identity routes add. */
export const wrongCode = (triesLeft: number) => ({
  resourceType: 'OperationOutcome',
  issue: [{ severity: 'error', code: 'invalid', diagnostics: 'That code is not right' }],
  triesLeft,
});
export const newCodeNeeded = (triesLeft = 0) => ({
  resourceType: 'OperationOutcome',
  issue: [{ severity: 'error', code: 'invalid', diagnostics: 'Ask for a new code' }],
  triesLeft,
});

/** Answers `path` (a back-end path) with `status` and `body`, keeping each call. */
export function backendAnswers(method: 'get' | 'post' | 'delete', path: string, status: number, body: unknown, headers: Record<string, string> = {}): RequestHandler {
  return http[method](`${BACKEND}${path}`, async ({ request }) => {
    seenBackend.push({
      method: request.method,
      path: new URL(request.url).pathname,
      host: request.headers.get('host'),
      authorization: request.headers.get('authorization'),
      body: request.method === 'GET' ? undefined : await request.json().catch(() => undefined),
    });
    return HttpResponse.json(body as Record<string, unknown>, { status, headers });
  });
}

export function answer(...handlers: RequestHandler[]) {
  server.use(...handlers);
}

export async function phoneCall(
  route: (request: Request, context: never) => Promise<Response> | Response,
  path: string,
  body: unknown,
  options: PreSessionOptions = {},
  context: unknown = { params: Promise.resolve({}) },
) {
  const raw = typeof body === 'string' ? body : JSON.stringify(body);
  return route(
    await requestPreSession({ host: A.host, path, body: raw, method: 'POST', headers: { 'Content-Type': 'application/json' }, ...options }),
    context as never,
  );
}
