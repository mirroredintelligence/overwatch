import { withBff } from '@/lib/bff/handler';
import { CONSOLE_ROLES, consoleCall, NO_STORE } from '@/lib/console/backend';

// Search for sessions (W48). Only the filters named here are forwarded, and each one is checked
// first. Search answers counts and session ids only; the timeline needs a code or a ticket.

const ROLES = ['reporter', 'advisor', 'clinical', 'lead', 'owner', 'exec', 'wall', 'support', 'audit'];
const RELEASE = /^\d+\.\d+\.\d+$/;
const SEARCH_ID = /^[A-Za-z0-9_-]{1,64}$/;
const SINCE_MAX = 40;

const get = withBff(
  async (request, session) => {
    const params = new URL(request.url).searchParams;
    const forwarded = new URLSearchParams();
    const sessionId = params.get('sessionId');
    const traceId = params.get('traceId');
    const reference = params.get('reference');
    const role = params.get('role');
    const release = params.get('release');
    const since = params.get('since');

    if (sessionId !== null) {
      if (!SEARCH_ID.test(sessionId)) return refused();
      forwarded.set('sessionId', sessionId);
    }
    if (traceId !== null) forwarded.set('traceId', traceId);
    if (reference !== null && reference.length <= 32) forwarded.set('reference', reference);
    if (role !== null) {
      if (!ROLES.includes(role)) return refused();
      forwarded.set('role', role);
    }
    if (release !== null) {
      if (!RELEASE.test(release)) return refused();
      forwarded.set('release', release);
    }
    if (since !== null) {
      if (since.length > SINCE_MAX) return refused();
      forwarded.set('since', since);
    }

    const query = forwarded.toString();
    const { data } = await consoleCall<{ items: unknown[] }>(
      session,
      `/support/sessions${query ? `?${query}` : ''}`,
    );
    return Response.json({ items: data.items }, { headers: NO_STORE });
  },
  { roles: [...CONSOLE_ROLES] },
);

function refused(): Response {
  return Response.json({ code: 'invalid' }, { status: 400, headers: NO_STORE });
}

export const GET = (request: Request) => get(request, undefined);
