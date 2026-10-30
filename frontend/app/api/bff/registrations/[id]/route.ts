import { withBff } from '@/lib/bff/handler';
import { readRegistration } from '@/lib/register/backend';
import { organisationAnswers } from '@/lib/register/draft';
import { bffJson, refuse } from '@/lib/register/requests';
import type { RegistrationView, StepValues } from '@/lib/register/types';

// The registration the applicant is working on (W54). The BFF passes on the status, the invitation's
// values and the saved answers of each step, in the screen's own field names, and nothing else the
// back end holds. The browser never sees the back-end token.

type Context = { params: Promise<{ id: string }> };

const ID = /^[A-Za-z0-9-]{1,64}$/;

/** The page's view of one saved step. Only the organisation step has a mapping so far (W54). */
function pageSteps(view: RegistrationView): Record<string, StepValues> {
  const steps: Record<string, StepValues> = {};
  const organisation = view.steps?.organisation;
  if (organisation !== undefined) steps.organisation = organisationAnswers(organisation);
  return steps;
}

const get = withBff<Context>(
  async (_request, session, context) => {
    const { id } = await context.params;
    if (!ID.test(id)) return refuse(404, 'not-found', 'We could not find that.');
    const view = await readRegistration(session.backendToken, id);
    return bffJson(200, {
      id: view.id,
      status: view.status,
      invitation: {
        serviceName: view.invitation.serviceName,
        organisationName: view.invitation.organisationName,
        odsCode: view.invitation.odsCode,
      },
      steps: pageSteps(view),
    });
  },
  { roles: ['reporter'] },
);

export async function GET(request: Request, context: Context): Promise<Response> {
  return get(request, context);
}
