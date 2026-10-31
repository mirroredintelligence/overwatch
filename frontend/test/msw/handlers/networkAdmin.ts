import { http, HttpResponse } from 'msw';
import { NETWORK, VIEW_GRANTS, VIEW_LISTINGS, VIEW_NETWORKS, VIEW_OVERVIEW, VIEW_SHARING_PAGE } from '@/test/fixtures/networkAdmin';

// The network administrator's BFF routes for component tests (TEN-080): the answers are what the BFF gives the
// browser (test/fixtures/networkAdmin.ts). A write is recorded with the CSRF token it carried, its path, its
// query and the body it sent. A test that needs another answer uses server.use(...).

export type SeenNetworkAdminWrite = { method: string; path: string; query: string; csrf: string | null; body: unknown };

export const seenNetworkAdminWrites: SeenNetworkAdminWrite[] = [];
export function resetNetworkAdminWrites() {
  seenNetworkAdminWrites.length = 0;
}
/** Every read the screens made, as `path?query`. */
export const seenNetworkAdminReads: string[] = [];
export function resetNetworkAdminReads() {
  seenNetworkAdminReads.length = 0;
}

const NO_STORE = { 'Cache-Control': 'no-store' };

async function recorded(request: Request) {
  let body: unknown;
  try {
    body = await request.clone().json();
  } catch {
    body = undefined;
  }
  const url = new URL(request.url);
  seenNetworkAdminWrites.push({ method: request.method, path: url.pathname, query: url.search.slice(1), csrf: request.headers.get('x-csrf-token'), body });
}

/** A resolver that answers `body` and records the read, for a test that overrides a read and still counts it. */
export function read(body: unknown) {
  return ({ request }: { request: Request }) => {
    const url = new URL(request.url);
    seenNetworkAdminReads.push(`${url.pathname}${url.search}`);
    return HttpResponse.json(body as Record<string, unknown>, { headers: NO_STORE });
  };
}

export const networkAdminHandlers = [
  http.get('/api/bff/network-admin/networks', read(VIEW_NETWORKS)),
  http.get('/api/bff/network-admin/grants', read(VIEW_GRANTS)),
  http.get('/api/bff/network-admin/listings', read(VIEW_LISTINGS)),
  http.get('/api/bff/network-admin', read(VIEW_OVERVIEW)),
  http.post('/api/bff/network-admin/members', async ({ request }) => {
    await recorded(request);
    return HttpResponse.json({ id: 'mem-new', status: 'invited' }, { status: 201, headers: NO_STORE });
  }),
  http.post('/api/bff/network-admin/members/:id/remove', async ({ request }) => {
    await recorded(request);
    return HttpResponse.json({ status: 'removed', grantsLapsed: 2, listingsWithdrawn: 1 }, { headers: NO_STORE });
  }),
  http.post('/api/bff/network-admin/agreement', async ({ request }) => {
    await recorded(request);
    const body = (await request.clone().json()) as { version: number };
    return HttpResponse.json({ agreementVersion: body.version }, { headers: NO_STORE });
  }),
  http.post('/api/bff/network-admin/grants/:id/approve', async ({ request }) => {
    await recorded(request);
    return HttpResponse.json({ effective: false }, { headers: NO_STORE });
  }),
  http.post('/api/bff/network-admin/grants/:id/decline', async ({ request }) => {
    await recorded(request);
    return HttpResponse.json({ status: 'declined' }, { headers: NO_STORE });
  }),
  // The member administrator's sharing routes (TEN-081).
  http.get('/api/bff/sharing', read(VIEW_SHARING_PAGE)),
  http.post('/api/bff/sharing/grants', async ({ request }) => {
    await recorded(request);
    return HttpResponse.json({ id: 'grant-new', status: 'proposed' }, { status: 201, headers: NO_STORE });
  }),
  http.post('/api/bff/sharing/grants/:id/approve', async ({ request }) => {
    await recorded(request);
    return HttpResponse.json({ effective: false }, { headers: NO_STORE });
  }),
  http.post('/api/bff/sharing/grants/:id/decline', async ({ request }) => {
    await recorded(request);
    return HttpResponse.json({ status: 'declined' }, { headers: NO_STORE });
  }),
  http.post('/api/bff/sharing/grants/:id/end', async ({ request }) => {
    await recorded(request);
    return HttpResponse.json({ status: 'ended' }, { headers: NO_STORE });
  }),
  http.post('/api/bff/sharing/leave', async ({ request }) => {
    await recorded(request);
    return HttpResponse.json({ status: 'left', grantsLapsed: 1, listingsWithdrawn: 0 }, { headers: NO_STORE });
  }),
  http.post('/api/bff/sharing/agreement', async ({ request }) => {
    await recorded(request);
    return HttpResponse.json({ status: 'active' }, { headers: NO_STORE });
  }),
  ...(['admit', 'reinstate', 'decline', 'suspend'] as const).map((action) =>
    http.post(`/api/bff/network-admin/listings/:id/${action}`, async ({ request }) => {
      await recorded(request);
      return HttpResponse.json({ status: 'done' }, { headers: NO_STORE });
    }),
  ),
];

export { NETWORK };
