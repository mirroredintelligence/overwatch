import { fromServiceRequest } from '@/lib/advisor/case-fhir';
import { readCase } from '@/lib/advisor/case-api';
import { answer, refuse } from '@/lib/advisor/http';
import { CASE_ROLES } from '@/lib/advisor/roles';
import { summaryOf } from '@/lib/advisor/summary';
import { withBff } from '@/lib/bff/handler';

// The SystmOne summary of one case (W15): read only, display strings only.

const CASE_ID = /^[A-Za-z0-9_-]{1,64}$/;
type Context = { params: Promise<{ ref: string }> };

const get = withBff<Context>(
  async (_request, session, context) => {
    const { ref } = await context.params;
    if (!CASE_ID.test(ref)) return refuse(400, 'invalid');
    const reply = await readCase(session.backendToken, ref);
    const view = fromServiceRequest(reply.data, reply.etag);
    if (view === null) return refuse(502, 'exception');
    // A closed case has no postcode or needs left (D18), so there is nothing to copy.
    if (view.closed) return refuse(409, 'closed');
    return answer(summaryOf(view));
  },
  { roles: [...CASE_ROLES], idScoped: true },
);

export const GET = (request: Request, context: Context) => get(request, context);
