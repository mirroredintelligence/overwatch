import { withBff } from '@/lib/bff/handler';
import { relayEvents } from '@/lib/bff/events';
import { fhirStream } from '@/lib/fhir/client';
import { NETWORK_VIEW_ROLES, requireOffered } from '@/lib/network/availability';
import { networkIdOf } from '@/lib/network/server';

// The network's live-update stream (TEN-068): the back end's `GET /network/{id}/events`, relayed for the
// signed-in session. The network is the `networkId` the server offered, checked against the registry
// BEFORE the stream is opened, so a tenant that is not a member opens nothing and a call carries no token
// to a network it cannot read. Only `network-board` (the time of a change) and `scope-ended` (the viewer
// may no longer read it) are forwarded, cut down to that (lib/bff/events.ts). The upstream is closed when
// the browser goes away. The back end checks the registry again while the stream is open.

// Never prerendered or cached: this is a live connection.
export const dynamic = 'force-dynamic';

const STREAM_HEADERS = {
  'Content-Type': 'text/event-stream; charset=utf-8',
  'Cache-Control': 'no-store, no-transform',
  'X-Accel-Buffering': 'no',
};

const get = withBff(
  async (request, session) => {
    const networkId = networkIdOf(request);
    await requireOffered(session, networkId);

    const closeUpstream = new AbortController();
    request.signal.addEventListener('abort', () => closeUpstream.abort(), { once: true });
    if (request.signal.aborted) closeUpstream.abort();

    const { body } = await fhirStream(`/network/${networkId}/events`, { token: session.backendToken, signal: closeUpstream.signal, root: true });
    return new Response(relayEvents(body, { signal: closeUpstream.signal, onCancel: () => closeUpstream.abort(), events: 'network' }), {
      status: 200,
      headers: STREAM_HEADERS,
    });
  },
  { roles: NETWORK_VIEW_ROLES, allowNetworkId: true, idScoped: true },
);

export const GET = (request: Request) => get(request, undefined);
