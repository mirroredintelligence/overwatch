import { withBff } from '@/lib/bff/handler';
import { notServed } from '@/lib/registration/backend';
import { idOf } from '@/lib/registration/request';
import { readRegistration } from '@/lib/register/backend';
import { organisationAnswers } from '@/lib/register/draft';
import { bffJson, refuse } from '@/lib/register/requests';
import type { RegistrationView, StepValues } from '@/lib/register/types';

// Two readers share this path: the applicant (reporter) reads the registration they are working on (W54);
// a lead reads its review overview (W28), which the back end does not serve yet (R10), so that answers
// 503 `not-supported` until it does. The role decides which.
//
// The registration the applicant is working on (W54). The BFF passes on the status, the invitation's
// values and the saved answers of each step, in the screen's own field names, and nothing else the
// back end holds. The browser never sees the back-end token.

type Context = { params: Promise<{ id: string }> };

const ID = /^[A-Za-z0-9-]{1,64}$/;

/**
 * The page's view of the saved steps. The organisation's answers (W54) and the location's fixed-site
 * answer (W25 needs it for the districts rule) are passed on; nothing else of a step is.
 */
function pageSteps(view: RegistrationView): Record<string, StepValues> {
  const steps: Record<string, StepValues> = {};
  const organisation = view.steps?.organisation;
  if (organisation !== undefined) steps.organisation = organisationAnswers(organisation);
  const location = view.steps?.location;
  if (location !== undefined && typeof location.fixedSite === 'boolean') steps.location = { fixedSite: location.fixedSite };
  return steps;
}

const get = withBff<Context>(
  async (_request, session, context) => {
    const { id } = await context.params;
    if (session.role === 'lead') {
      idOf(id);
      notServed();
    }
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
  { idScoped: true, roles: ['reporter', 'lead'] },
);

export async function GET(request: Request, context: Context): Promise<Response> {
  return get(request, context);
}
