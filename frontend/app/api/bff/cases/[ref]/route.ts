import { readCase, updateCase } from '@/lib/advisor/case-api';
import { fromServiceRequest, toServiceRequest } from '@/lib/advisor/case-fhir';
import { parseCaseInput } from '@/lib/advisor/codes';
import { answer, idempotencyKeyOf, refuse } from '@/lib/advisor/http';
import { CASE_ROLES } from '@/lib/advisor/roles';
import { withBff } from '@/lib/bff/handler';
import { FhirError } from '@/lib/fhir/client';

// One case, read and saved by the advisor's own session (W11). The case id is the only input, and it
// is checked for shape before anything is read. A save needs the ETag from the read (If-Match) and an
// Idempotency-Key: the back end requires both (concurrency.py). A stale ETag answers 412 with the code
// "conflict". An id the back end does not know, or that is another tenant's, is the one 404 (idScoped).

const CASE_ID = /^[A-Za-z0-9_-]{1,64}$/;

type Context = { params: Promise<{ ref: string }> };

async function caseIdOf(context: Context): Promise<string | null> {
  const { ref } = await context.params;
  return CASE_ID.test(ref) ? ref : null;
}

const get = withBff<Context>(
  async (_request, session, context) => {
    const id = await caseIdOf(context);
    if (id === null) return refuse(400, 'invalid');
    const reply = await readCase(session.backendToken, id);
    const view = fromServiceRequest(reply.data, reply.etag);
    if (view === null) return refuse(502, 'exception');
    return answer(view);
  },
  { roles: [...CASE_ROLES], idScoped: true },
);

const put = withBff<Context>(
  async (request, session, context) => {
    const id = await caseIdOf(context);
    if (id === null) return refuse(400, 'invalid');
    const ifMatch = request.headers.get('If-Match');
    if (ifMatch === null || ifMatch === '') return refuse(428, 'precondition');
    const key = idempotencyKeyOf(request);
    if (key === null) return refuse(400, 'invalid');

    let body: unknown;
    try {
      body = await request.json();
    } catch {
      return refuse(400, 'invalid');
    }
    const input = parseCaseInput(body);
    if (input === null) return refuse(400, 'invalid');

    try {
      const reply = await updateCase(session.backendToken, id, toServiceRequest(id, input), ifMatch, key);
      const view = fromServiceRequest(reply.data, reply.etag);
      if (view === null) return refuse(502, 'exception');
      return answer(view);
    } catch (error) {
      if (error instanceof FhirError && error.status === 412) return refuse(412, 'conflict');
      throw error;
    }
  },
  { roles: [...CASE_ROLES], idScoped: true },
);

export const GET = (request: Request, context: Context) => get(request, context);
export const PUT = (request: Request, context: Context) => put(request, context);
