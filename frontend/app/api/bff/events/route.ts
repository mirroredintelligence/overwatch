import { withBff } from '@/lib/bff/handler';
import { relayEvents } from '@/lib/bff/events';
import { BOARD_ROLES } from '@/lib/board/read';
import { fhirStream } from '@/lib/fhir/client';

// The browser's live-update stream: the back end's GET /events, relayed for the
// signed-in session. It takes no input: no tenant, scope or organisation comes
// from the URL, the query string or a header; the stream is the one the session's
// back-end token is for (DEC-130, DEC-132). Only the events the pages use are
// forwarded (lib/bff/events.ts). The upstream is closed when the browser goes away.

// Never prerendered or cached: this is a live connection.
export const dynamic = 'force-dynamic';

const STREAM_HEADERS = {
  'Content-Type': 'text/event-stream; charset=utf-8',
  // no-transform keeps compression from buffering the stream; no-store keeps every cache out.
  'Cache-Control': 'no-store, no-transform',
  'X-Accel-Buffering': 'no',
};

const get = withBff(
  async (request, session) => {
    const closeUpstream = new AbortController();
    request.signal.addEventListener('abort', () => closeUpstream.abort(), { once: true });
    if (request.signal.aborted) closeUpstream.abort();

    const { body } = await fhirStream('/events', { token: session.backendToken, signal: closeUpstream.signal });
    return new Response(relayEvents(body, { signal: closeUpstream.signal, onCancel: () => closeUpstream.abort() }), { status: 200, headers: STREAM_HEADERS });
  },
  { roles: [...BOARD_ROLES] },
);

// Route handlers receive a context this route does not use.
export const GET = (request: Request) => get(request, undefined);
