import { closeCase } from '@/lib/advisor/case-api';
import { fromServiceRequest } from '@/lib/advisor/case-fhir';
import { idempotencyKeyOf, answer, refuse } from '@/lib/advisor/http';
import { parseOutcomeInput } from '@/lib/advisor/outcome';
import { CASE_ROLES } from '@/lib/advisor/roles';
import { withBff } from '@/lib/bff/handler';

// Records the outcome and closes the case (W15). The answer is the close time the back end recorded,
// read from the closed ServiceRequest (DEC-781); if the answer is not a closed case there is no time to
// give and the route says so (502) rather than make one up.

const CASE_ID = /^[A-Za-z0-9_-]{1,64}$/;
type Context = { params: Promise<{ ref: string }> };

const post = withBff<Context>(
  async (request, session, context) => {
    const { ref } = await context.params;
    if (!CASE_ID.test(ref)) return refuse(400, 'invalid');
    const key = idempotencyKeyOf(request);
    if (key === null) return refuse(400, 'invalid');

    let body: unknown;
    try {
      body = await request.json();
    } catch {
      return refuse(400, 'invalid');
    }
    const input = parseOutcomeInput(body);
    if (input === null) return refuse(400, 'invalid');

    const reply = await closeCase(session.backendToken, ref, input, key);
    const closed = fromServiceRequest(reply.data, reply.etag);
    if (closed === null || !closed.closed || closed.closedAt === null) return refuse(502, 'exception');
    return answer({ closedAt: closed.closedAt });
  },
  { roles: [...CASE_ROLES], idScoped: true },
);

export const POST = (request: Request, context: Context) => post(request, context);
