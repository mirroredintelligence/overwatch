import { randomUUID } from 'node:crypto';
import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { checkProblem } from '@/lib/help/report';
import type { Role } from '@/lib/auth/session';

// A problem report with the tool (W46, R13 `POST /help/problems`, W7A DEC-778). The request is checked here
// as the back end checks it, then sent as its category and text. The page the person was on is checked but
// not sent: the back end holds no page route (known issue W7A-K5). The answer is the report's id and never
// the text. Nothing is stored or logged here. The route is at the back end's root, not under /fhir.

const NO_STORE = { 'Cache-Control': 'no-store' };
const ROLES: Role[] = ['reporter', 'advisor', 'clinical', 'lead', 'owner', 'exec', 'support', 'audit'];

const post = withBff(
  async (request, session) => {
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      body = undefined;
    }
    const checked = checkProblem(body);
    if (!checked.ok) return Response.json({ code: 'invalid', message: 'The request was not valid.' }, { status: 400, headers: NO_STORE });
    const { kind, text } = checked.value;
    const { data } = await fhirFetch<{ id?: unknown }>('/help/problems', {
      method: 'POST',
      token: session.backendToken,
      body: { category: kind, ...(text === undefined ? {} : { text }) },
      idempotencyKey: randomUUID(),
      root: true,
    });
    if (typeof data.id !== 'string') throw new Error('The back end sent no report id.');
    return Response.json({ id: data.id }, { status: 201, headers: NO_STORE });
  },
  { roles: ROLES },
);

export const POST = (request: Request) => post(request, undefined);
