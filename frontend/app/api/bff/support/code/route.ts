import { randomUUID } from 'node:crypto';
import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { checkCodeRequest, isSessionId } from '@/lib/support/share';
import type { Role } from '@/lib/auth/session';

// Share my session with support (W56, R18). GET says whether a code is live for this session and until
// when, never the code (W7A, DEC-772: only a keyed hash of it is kept). POST makes a code for this session
// and returns it once; DELETE stops sharing it. A support person cannot share; a wall screen and a link
// cannot either. The code is never stored by the BFF or written to a log. The routes are at the back end's
// root, not under /fhir.

const NO_STORE = { 'Cache-Control': 'no-store' };
const ROLES: Role[] = ['reporter', 'advisor', 'clinical', 'lead', 'owner', 'exec', 'audit'];

function invalid(): Response {
  return Response.json({ code: 'invalid', message: 'The request was not valid.' }, { status: 400, headers: NO_STORE });
}

const get = withBff(
  async (request, session) => {
    const sessionId = new URL(request.url).searchParams.get('sessionId');
    if (!isSessionId(sessionId)) return invalid();
    const { data } = await fhirFetch<{ active?: unknown; expiresAt?: unknown }>(`/support/codes/current?sessionId=${sessionId}`, {
      token: session.backendToken,
      root: true,
    });
    if (data.active !== true) return Response.json({ active: false }, { headers: NO_STORE });
    if (typeof data.expiresAt !== 'string') throw new Error('The back end sent no end time.');
    return Response.json({ active: true, expiresAt: data.expiresAt }, { headers: NO_STORE });
  },
  { roles: ROLES },
);

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
      root: true,
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
      root: true,
    });
    return new Response(null, { status: 204, headers: NO_STORE });
  },
  { roles: ROLES },
);

export const GET = (request: Request) => get(request, undefined);
export const POST = (request: Request) => post(request, undefined);
export const DELETE = (request: Request) => del(request, undefined);
