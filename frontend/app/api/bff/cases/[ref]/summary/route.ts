import { readSummary } from '@/lib/advisor/case-api';
import { answer, refuse } from '@/lib/advisor/http';
import { CASE_ROLES } from '@/lib/advisor/roles';
import { summaryFromParameters } from '@/lib/advisor/summary';
import { withBff } from '@/lib/bff/handler';
import { FhirError } from '@/lib/fhir/client';

// The SystmOne summary of one open case (W15, H-322): read only, display strings only. The back end builds
// it (BuildCaseSummary), so the text that is pasted is the text it holds, with the destination, the booking
// and the data age of the service named in `?destination=` (the service the advisor chose on the outcome
// form). A closed case has no summary: the back end says so and the route answers 409 closed.

const CASE_ID = /^[A-Za-z0-9_-]{1,64}$/;
const SERVICE_ID = /^[A-Za-z0-9.-]{1,64}$/;
type Context = { params: Promise<{ ref: string }> };

const get = withBff<Context>(
  async (request, session, context) => {
    const { ref } = await context.params;
    if (!CASE_ID.test(ref)) return refuse(400, 'invalid');
    const destination = new URL(request.url).searchParams.get('destination');
    if (destination !== null && !SERVICE_ID.test(destination)) return refuse(400, 'invalid');
    try {
      const view = summaryFromParameters(await readSummary(session.backendToken, ref, destination), destination !== null);
      if (view === null) return refuse(502, 'exception');
      return answer(view);
    } catch (error) {
      if (error instanceof FhirError && error.status === 409) return refuse(409, 'closed');
      throw error;
    }
  },
  { roles: [...CASE_ROLES], idScoped: true },
);

export const GET = (request: Request, context: Context) => get(request, context);
