import { withBff } from '@/lib/bff/handler';
import { hostOf } from '@/lib/links/server';
import { json, screenFailure } from '@/lib/screens/answers';
import { parseCode } from '@/lib/screens/model';
import { previewScreen } from '@/lib/screens/server';
import { readTenantProfile } from '@/lib/tenant/profile';

// The confirm step of pairing (TEN-072, docs/design/network-ui.md section 6, ScreenClaim): a shift lead
// types the code and is shown which organisation the screen will show and when the screen first asked,
// before connecting it. Lead only, CSRF checked. The tenant is the lead's token's: the body is the code
// and nothing else (any other key is a 400), and nothing in it, the query or a header can name one. The
// back end burns and writes nothing and counts a wrong code against the connect's allowance. The
// organisation's name is the tenant's own, from its profile; when it cannot be read it is null and the
// page says "your organisation".

const MAX_BODY_BYTES = 256;
const NOT_FOUND = 'That code is not valid or has expired. Check the screen for a new code.';

const invalid = (field?: string) =>
  json(400, field === undefined ? { code: 'invalid', message: 'The request was not valid.' } : { code: 'invalid', field, message: 'The request was not valid.' });

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
    if (Object.keys(source).some((key) => key !== 'code')) return invalid();
    const code = parseCode(source.code);
    if (!code.ok) return invalid('code');

    const host = hostOf(request);
    try {
      const preview = await previewScreen(host, session.backendToken, code.value);
      const profile = await readTenantProfile(host);
      return json(200, { organisationName: profile?.displayName ?? null, firstSeenAt: preview.firstSeenAt, deviceClass: preview.deviceClass });
    } catch (error) {
      return screenFailure(error, { notFound: NOT_FOUND });
    }
  },
  { roles: ['lead'] },
);

// Route handlers receive a context this route does not use.
export const POST = (request: Request) => post(request, undefined);
