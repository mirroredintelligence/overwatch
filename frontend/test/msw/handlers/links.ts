import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { BACKEND_ROOT, LINK, linkAnswerReply, linkRenewReply, linkViewReply, TENANT_HOST, type LinkReplyFor } from '@/test/fixtures/links';

// The capacity link API as the back end answers it (L01, DEC-167), for the link pages' tests,
// from the shared scenario table in test/fixtures/links.ts (the browser tests use the same table).
// The BFF's answers are the same shapes at the browser's relative paths. Every POST the page makes
// is kept, so a test can assert that opening a page sent none.

/** Every POST the browser sent to the BFF, newest last. */
export const seenBffPosts: { token: string; body: unknown; csrf: string | null }[] = [];
/** Every renewal the browser asked the BFF for, newest last. */
export const seenBffRenews: string[] = [];
/** Every request the back end stand-in saw, with the Host it was sent to. */
export const seenBackendRequests: { method: string; token: string; host: string | null; body: unknown }[] = [];

export function resetLinkRequests() {
  seenBffPosts.length = 0;
  seenBffRenews.length = 0;
  seenBackendRequests.length = 0;
}

function reply({ status, body, headers }: LinkReplyFor) {
  return HttpResponse.json(body as Record<string, unknown>, {
    status,
    headers: { 'Cache-Control': 'no-store', ...headers },
  });
}

async function jsonBody(request: Request): Promise<Record<string, unknown>> {
  const parsed = (await request.json().catch(() => null)) as unknown;
  return typeof parsed === 'object' && parsed !== null ? (parsed as Record<string, unknown>) : {};
}

/** The back end stand-in: `GET /links/{token}`, `POST /links/{token}` and `POST /links/{token}/renew`. */
// The sample links belong to one tenant: the tenant of TENANT_HOST. Like the real back end (DEC-167
// item 1), a request addressed to another tenant's host finds no such link and answers as it does for
// a link that exists nowhere (TEN-047).
const OWN_HOST = TENANT_HOST;
const ABSENT = { status: 410, body: { state: 'expired' } } as LinkReplyFor;
const ownHost = (request: Request) => request.headers.get('host') === OWN_HOST;

export const backendLinkHandlers = [
  http.get(`${BACKEND_ROOT}/links/:token`, (({ request, params }) => {
    const token = String(params.token);
    seenBackendRequests.push({ method: 'GET', token, host: request.headers.get('host'), body: undefined });
    return reply(ownHost(request) ? linkViewReply(token) : ABSENT);
  }) as HttpResponseResolver),
  http.post(`${BACKEND_ROOT}/links/:token`, (async ({ request, params }) => {
    const token = String(params.token);
    const body = await jsonBody(request);
    seenBackendRequests.push({ method: 'POST', token, host: request.headers.get('host'), body });
    return reply(ownHost(request) ? linkAnswerReply(token, request.headers.get('x-csrf-token'), body) : ABSENT);
  }) as HttpResponseResolver),
  http.post(`${BACKEND_ROOT}/links/:token/renew`, (({ request, params }) => {
    const token = String(params.token);
    seenBackendRequests.push({ method: 'POST', token, host: request.headers.get('host'), body: undefined });
    return reply(linkRenewReply(token));
  }) as HttpResponseResolver),
];

/** The BFF as the browser sees it: the same answers at its own relative paths. */
export const bffLinkHandlers = [
  http.get('/api/bff/links/:token', (({ params }) => reply(linkViewReply(String(params.token)))) as HttpResponseResolver),
  http.post('/api/bff/links/:token', (async ({ request, params }) => {
    const token = String(params.token);
    const body = await jsonBody(request);
    seenBffPosts.push({ token, body, csrf: request.headers.get('x-csrf-token') });
    return reply(linkAnswerReply(token, request.headers.get('x-csrf-token'), body));
  }) as HttpResponseResolver),
  http.post('/api/bff/links/:token/renew', (({ params }) => {
    const token = String(params.token);
    seenBffRenews.push(token);
    return reply(linkRenewReply(token));
  }) as HttpResponseResolver),
];

export const linkHandlers = [...backendLinkHandlers, ...bffLinkHandlers];
export { LINK };
