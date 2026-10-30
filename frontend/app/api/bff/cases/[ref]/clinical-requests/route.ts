import { randomUUID } from 'node:crypto';
import { REQUEST_URGENCIES, REQUEST_WHYS } from '@/lib/clinical/advice';
import { withBff } from '@/lib/bff/handler';
import { codeSystemUrl } from '@/lib/fhir/codes';
import { fhirFetch } from '@/lib/fhir/client';
import type { Role } from '@/lib/auth/session';

// An advisor asks for clinical advice on a case (W45, R13 `POST /fhir/Task`). The case is the focus; the
// urgency and the reason are its inputs. The back end takes exactly these two values, and refuses others.

const NO_STORE = { 'Cache-Control': 'no-store' };
const CASE = /^[A-Za-z0-9-]{1,64}$/;
const ROLES: Role[] = ['advisor', 'lead'];

type Context = { params: Promise<{ ref: string }> };

const post = withBff<Context>(
  async (request, session, context) => {
    const { ref } = await context.params;
    if (!CASE.test(ref)) return Response.json({ code: 'not-found' }, { status: 404, headers: NO_STORE });
    let body: Record<string, unknown>;
    try {
      body = (await request.json()) as Record<string, unknown>;
    } catch {
      return Response.json({ code: 'invalid', message: 'The request was not valid.' }, { status: 400, headers: NO_STORE });
    }
    const urgency = body?.urgency;
    const why = body?.why;
    if (typeof urgency !== 'string' || !(REQUEST_URGENCIES as readonly string[]).includes(urgency)) {
      return Response.json({ code: 'invalid', message: 'The request was not valid.' }, { status: 400, headers: NO_STORE });
    }
    if (typeof why !== 'string' || !(REQUEST_WHYS as readonly string[]).includes(why)) {
      return Response.json({ code: 'invalid', message: 'The request was not valid.' }, { status: 400, headers: NO_STORE });
    }
    const task = {
      resourceType: 'Task',
      status: 'requested',
      code: { coding: [{ system: codeSystemUrl('task-code'), code: 'clinical-advice' }] },
      focus: { reference: `ServiceRequest/${ref}` },
      extension: [
        { url: codeSystemUrl('task-input/urgency'), valueCode: urgency },
        { url: codeSystemUrl('task-input/why'), valueCode: why },
      ],
    };
    const { data } = await fhirFetch<{ id?: unknown }>('/Task', {
      method: 'POST',
      token: session.backendToken,
      body: task,
      idempotencyKey: randomUUID(),
    });
    if (typeof data.id !== 'string') throw new Error('The back end sent no request id.');
    return Response.json({ requestId: data.id }, { status: 201, headers: NO_STORE });
  },
  { roles: ROLES, idScoped: true },
);

export const POST = (request: Request, context: Context) => post(request, context);
