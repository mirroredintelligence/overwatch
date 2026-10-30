import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { isSessionId } from '@/lib/support/share';
import type { Role } from '@/lib/auth/session';

// Who has opened this session since the code was made (W56, R18). Each entry is when, and the role that
// opened it, and nothing about what they saw.

const NO_STORE = { 'Cache-Control': 'no-store' };
const ROLES: Role[] = ['reporter', 'advisor', 'clinical', 'lead', 'owner', 'exec', 'audit'];

const get = withBff(
  async (request, session) => {
    const sessionId = new URL(request.url).searchParams.get('sessionId');
    if (!isSessionId(sessionId)) {
      return Response.json({ code: 'invalid', message: 'The request was not valid.' }, { status: 400, headers: NO_STORE });
    }
    const { data } = await fhirFetch<{ openedAt: string; role: string }[]>(`/support/accesses?sessionId=${sessionId}`, {
      token: session.backendToken,
    });
    const accesses = (Array.isArray(data) ? data : []).map((view) => ({ openedAt: view.openedAt, role: view.role }));
    return Response.json(accesses, { headers: NO_STORE });
  },
  { roles: ROLES },
);

export const GET = (request: Request) => get(request, undefined);
