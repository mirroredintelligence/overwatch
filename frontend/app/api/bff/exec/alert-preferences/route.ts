import { AlertPreferencesError, parseAlertPreferences } from '@/lib/exec/alertPrefs';
import { readAlertPreferences, saveAlertPreferences } from '@/lib/exec/subscriptions';
import { withBff } from '@/lib/bff/handler';
import type { Role } from '@/lib/auth/session';

// The executive's and the shift lead's own alert preferences (W39). A practitioner reads and changes
// only their own: the back end's subscription is the token's subject, and this route takes no id, no
// tenant and no practitioner from the browser. A refused value is a 400 that names nothing.

const NO_STORE = { 'Cache-Control': 'no-store' };
const ROLES: Role[] = ['exec', 'lead'];

function invalid(): Response {
  return Response.json({ code: 'invalid', message: 'The request was not valid.' }, { status: 400, headers: NO_STORE });
}

const get = withBff(
  async (_request, session) => {
    const stored = await readAlertPreferences(session);
    return Response.json(stored.preferences, { headers: NO_STORE });
  },
  { roles: ROLES },
);

const put = withBff(
  async (request, session) => {
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      return invalid();
    }
    let prefs;
    try {
      prefs = parseAlertPreferences(body);
    } catch (error) {
      if (error instanceof AlertPreferencesError) return invalid();
      throw error;
    }
    const saved = await saveAlertPreferences(session, prefs);
    return Response.json(saved, { headers: NO_STORE });
  },
  { roles: ROLES },
);

// Route handlers receive a context this route does not use.
export const GET = (request: Request) => get(request, undefined);
export const PUT = (request: Request) => put(request, undefined);
