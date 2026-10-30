import { randomUUID } from 'node:crypto';
import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { checkCodeRequest, isSessionId } from '@/lib/support/share';
import type { Role } from '@/lib/auth/session';

// Share my session with support (W56, R18). POST makes a code for this session; DELETE stops sharing it.
// A support person cannot share; a wall screen and a link cannot either. The code is returned once and
// is never stored by the BFF or written to a log.

const NO_STORE = { 'Cache-Control': 'no-store' };
const ROLES: Role[] = ['reporter', 'advisor', 'clinical', 'lead', 'owner', 'exec', 'audit'];

function invalid(): Response {
  return Response.json({ code: 'invalid', message: 'The request was not valid.' }, { status: 400, headers: NO_STORE });
}

const post = withBff(
  async (request, session) => {
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      return invalid();
    }
    const checked = checkCodeRequest(body);
    if (checked === null) return invalid();
    const { data } = await fhirFetch<{ code?: unknown; expiresAt?: unknown }>('/support/codes', {
      method: 'POST',
      token: session.backendToken,
      body: checked,
      idempotencyKey: randomUUID(),
    });
    if (typeof data.code !== 'string' || typeof data.expiresAt !== 'string') throw new Error('The back end sent no code.');
    return Response.json({ code: data.code, expiresAt: data.expiresAt }, { status: 201, headers: NO_STORE });
  },
  { roles: ROLES },
);

const del = withBff(
  async (request, session) => {
    const sessionId = new URL(request.url).searchParams.get('sessionId');
    if (!isSessionId(sessionId)) return invalid();
    await fhirFetch(`/support/codes/current?sessionId=${sessionId}`, {
      method: 'DELETE',
      token: session.backendToken,
      idempotencyKey: randomUUID(),
    });
    return new Response(null, { status: 204, headers: NO_STORE });
  },
  { roles: ROLES },
);

export const POST = (request: Request) => post(request, undefined);
export const DELETE = (request: Request) => del(request, undefined);
