import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { PairingStandIn, type StandInReply } from '@/test/fixtures/pairing';
import { BACKEND_ROOT } from '@/test/oidc/constants';

// The back end's wall screen pairing (R15) for the BFF's tests, from the stand-in in
// test/fixtures/pairing.ts. Not in the default handlers: the tests that pair a screen add them.

export const pairingBackend = new PairingStandIn();

function send(reply: StandInReply) {
  return HttpResponse.json(reply.body as Record<string, unknown>, {
    status: reply.status,
    headers: { 'Cache-Control': 'no-store', ...reply.headers },
  });
}

async function json(request: Request): Promise<unknown> {
  return (await request.json().catch(() => undefined)) as unknown;
}

export const screenHandlers = [
  http.post(`${BACKEND_ROOT}/screens/pairing`, (({ request }) => send(pairingBackend.start(request.headers.get('host')))) as HttpResponseResolver),
  http.get(`${BACKEND_ROOT}/screens/pairing/:id`, (({ request, params }) =>
    send(pairingBackend.claim(request.headers.get('host'), String(params.id), request.headers.get('x-screen-secret')))) as HttpResponseResolver),
  http.post(`${BACKEND_ROOT}/screens`, (async ({ request }) =>
    send(
      pairingBackend.connect(
        request.headers.get('host'),
        request.headers.get('authorization'),
        request.headers.get('idempotency-key'),
        await json(request),
      ),
    )) as HttpResponseResolver),
];
