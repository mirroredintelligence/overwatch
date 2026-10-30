import { randomUUID } from 'node:crypto';
import { withBff } from '@/lib/bff/handler';
import { codeSystemUrl } from '@/lib/fhir/codes';
import { fhirFetch } from '@/lib/fhir/client';
import { checkSafetyConcern } from '@/lib/help/report';
import type { Role } from '@/lib/auth/session';

// A safety concern (W46). It is a Task with the safety-concern code, the category and the text as its
// inputs (R13, `POST /fhir/Task`); the back end holds the text, and this route answers the reference only.
// Any signed-in person may report; a wall screen and a link may not.

const NO_STORE = { 'Cache-Control': 'no-store' };
const ROLES: Role[] = ['reporter', 'advisor', 'clinical', 'lead', 'owner', 'exec', 'support', 'audit'];

function input(name: string, key: 'valueCode' | 'valueString', value: string) {
  return { url: codeSystemUrl(`task-input/${name}`), [key]: value };
}

const post = withBff(
  async (request, session) => {
    let body: unknown;
    try {
      body = await request.json();
    } catch {
      body = undefined;
    }
    const checked = checkSafetyConcern(body);
    if (!checked.ok) return Response.json({ code: 'invalid', message: 'The request was not valid.' }, { status: 400, headers: NO_STORE });
    const { category, text, reference } = checked.value;
    const task = {
      resourceType: 'Task',
      status: 'requested',
      code: { coding: [{ system: codeSystemUrl('task-code'), code: 'safety-concern' }] },
      extension: [
        input('category', 'valueCode', category),
        input('text', 'valueString', text),
        ...(reference === undefined ? [] : [input('reference', 'valueString', reference)]),
      ],
    };
    const { data } = await fhirFetch<{ identifier?: { value?: unknown }[] }>('/Task', {
      method: 'POST',
      token: session.backendToken,
      body: task,
      idempotencyKey: randomUUID(),
    });
    const sent = data.identifier?.[0]?.value;
    if (typeof sent !== 'string') throw new Error('The back end sent no reference.');
    return Response.json({ reference: sent }, { headers: NO_STORE });
  },
  { roles: ROLES },
);

export const POST = (request: Request) => post(request, undefined);
