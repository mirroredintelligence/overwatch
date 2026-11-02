import { withBff } from '@/lib/bff/handler';
import { FhirError } from '@/lib/fhir/fhirError';
import { NO_STORE, tenantRead } from '@/lib/tenantAdmin/call';
import { parsePeople } from '@/lib/tenantAdmin/views';

// GET /tenant/people?q=: look people up in the organisation's own directory by the start of a name or address,
// for the add-a-person box (DEC-1325). The term is checked here by its shape (2 to 64 plain characters) before
// any call and passed on as it is; the back end checks it again. Nothing about the people found is stored.

const TERM = /^[A-Za-z0-9 .'@+_-]{2,64}$/;

function termOf(request: Request): string {
  const raw = new URL(request.url).searchParams.get('q')?.trim() ?? '';
  if (!TERM.test(raw)) {
    throw new FhirError(400, { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'invalid', diagnostics: 'invalid' }] });
  }
  return raw;
}

const get = withBff(
  async (request, session) => Response.json(parsePeople(await tenantRead(session, `/tenant/people?q=${encodeURIComponent(termOf(request))}`)), { headers: NO_STORE }),
  { roles: ['tenant-admin'] },
);

export const GET = (request: Request) => get(request, undefined);
