import { randomUUID } from 'node:crypto';
import { withBff } from '@/lib/bff/handler';
import { hostOf } from '@/lib/links/server';
import { json, screenFailure } from '@/lib/screens/answers';
import { parseCode, parseLocation, parseName } from '@/lib/screens/model';
import { connectScreen } from '@/lib/screens/server';

// A shift lead connects a wall display by typing the code it shows. Role lead, and the session's
// CSRF check. The tenant is the lead's token's: nothing in the body, the query or a header can name
// one, and only the fields of a connect are forwarded. A screen always shows the organisation's own
// board: the page offers no choice, so none is sent (the back end defaults to it).

const MAX_BODY_BYTES = 1024;
const INVALID = 'The request was not valid.';
const NOT_FOUND = 'That code is not valid or has expired. Check the screen for a new code.';

const invalid = (field?: string, message: string = INVALID) =>
  json(400, field === undefined ? { code: 'invalid', message } : { code: 'invalid', field, message });

const post = withBff(
  async (request, session) => {
    const text = await request.text();
    if (new TextEncoder().encode(text).length > MAX_BODY_BYTES) return invalid();
    let parsed: unknown;
    try {
      parsed = JSON.parse(text) as unknown;
    } catch {
      return invalid();
    }
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return invalid();
    const source = parsed as Record<string, unknown>;

    const code = parseCode(source.code);
    if (!code.ok) return invalid('code', code.error);
    const name = parseName(source.name);
    if (!name.ok) return invalid('name', name.error);
    const location = parseLocation(source.location);
    if (!location.ok) return invalid('location', location.error);

    try {
      const connected = await connectScreen(
        hostOf(request),
        session.backendToken,
        { code: code.value, name: name.value, location: location.value },
        randomUUID(),
      );
      return json(201, { name: connected.name, status: connected.status, connectedAt: new Date().toISOString() });
    } catch (error) {
      return screenFailure(error, { notFound: NOT_FOUND });
    }
  },
  { roles: ['lead'] },
);

// Route handlers receive a context this route does not use.
export const POST = (request: Request) => post(request, undefined);
