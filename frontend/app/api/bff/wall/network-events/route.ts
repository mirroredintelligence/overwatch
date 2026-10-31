import { withBff } from '@/lib/bff/handler';
import { relayEvents } from '@/lib/bff/events';
import { fhirStream } from '@/lib/fhir/client';

// The live-update stream of a wall screen that shows a network (TEN-072): the back end's
// `GET /screens/me/network-events`, relayed for the paired screen's session. The screen names no network:
// its record does, and the back end ends the stream with `scope-ended` when the screen or its organisation
// may no longer read it. A wall screen only: no person's role opens it. Only `network-board` (the time of a
// change) and `scope-ended` are forwarded, cut down to that. The upstream is closed when the browser goes.

// Never prerendered or cached: this is a live connection.
export const dynamic = 'force-dynamic';

const STREAM_HEADERS = {
  'Content-Type': 'text/event-stream; charset=utf-8',
  'Cache-Control': 'no-store, no-transform',
  'X-Accel-Buffering': 'no',
};

const get = withBff(
  async (request, session) => {
    const closeUpstream = new AbortController();
    request.signal.addEventListener('abort', () => closeUpstream.abort(), { once: true });
    if (request.signal.aborted) closeUpstream.abort();

    const { body } = await fhirStream('/screens/me/network-events', { token: session.backendToken, signal: closeUpstream.signal, root: true });
    return new Response(relayEvents(body, { signal: closeUpstream.signal, onCancel: () => closeUpstream.abort(), events: 'network' }), { status: 200, headers: STREAM_HEADERS });
  },
  { roles: ['wall'] },
);

// Route handlers receive a context this route does not use.
export const GET = (request: Request) => get(request, undefined);
