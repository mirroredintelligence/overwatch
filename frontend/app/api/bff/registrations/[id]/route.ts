import { withBff } from '@/lib/bff/handler';
import { idOf } from '@/lib/registration/request';
import { overviewFromBackend } from '@/lib/registration/mapping';
import { readOverview, readRegistration } from '@/lib/register/backend';
import { bffJson, refuse } from '@/lib/register/requests';
import type { RecordView, RecordStep } from '@/lib/register/applicant';
import type { StepValues } from '@/lib/register/types';

// Two readers share this path: the applicant (reporter) reads the registration they are working on (W54);
// a lead reads its review overview (W28), mapped by overviewFromBackend. The role decides which.
//
// The BFF passes on the service name and the saved answers of each step, in the screen's own field
// names, and nothing else the back end holds. The browser never sees the back-end token (DEC-904).

type Context = { params: Promise<{ id: string }> };

const ID = /^[A-Za-z0-9-]{1,64}$/;

/** The values a step page is given: a stored phone is its last three digits only (already so in the record). */
function pageValues(step: RecordStep | undefined): StepValues {
  return (step?.values ?? {}) as StepValues;
}

/** The page's view of the saved steps, in the names each step's screen uses. */
function pageSteps(view: RecordView): Record<string, StepValues> {
  const steps: Record<string, StepValues> = {};
  for (const name of ['organisation', 'location', 'service', 'reporting', 'api'] as const) {
    const step = view.steps[name];
    if (step !== undefined) steps[name] = pageValues(step);
  }
  return steps;
}

const get = withBff<Context>(
  async (_request, session, context) => {
    const { id } = await context.params;
    if (session.role === 'lead') {
      const overview = overviewFromBackend(await readOverview(session.backendToken, idOf(id)));
      if (overview === null) return refuse(503, 'unavailable', 'We could not load the review. Try again later.');
      return bffJson(200, overview);
    }
    if (!ID.test(id)) return refuse(404, 'not-found', 'We could not find that.');
    const view = await readRegistration(session.backendToken, id);
    return bffJson(200, { id: view.id, status: view.status, serviceName: view.serviceName, steps: pageSteps(view) });
  },
  { idScoped: true, roles: ['reporter', 'lead'] },
);

export async function GET(request: Request, context: Context): Promise<Response> {
  return get(request, context);
}
