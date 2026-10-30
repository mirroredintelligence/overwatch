import { FhirError } from '@/lib/fhir/client';
import { withBff } from '@/lib/bff/handler';
import { readRegistration, saveStep } from '@/lib/register/backend';
import { issuesFromOutcome, locationValues, organisationValues, STEP_FIELDS } from '@/lib/register/draft';
import { serviceValues } from '@/lib/register/service';
import { bffJson, jsonBody, refuse } from '@/lib/register/requests';
import { isStepName } from '@/lib/register/steps';
import type { StepName } from '@/lib/register/types';

// Saves one registration step (W54: the organisation step; W24 to W26 add the others). The browser
// sends its answers only. The invitation's values come from the back end, the back end checks the
// answers and answers the save, and a refusal comes back as the errors each field shows.

type Context = { params: Promise<{ id: string; step: string }> };

const ID = /^[A-Za-z0-9-]{1,64}$/;
/** The steps this route saves. The others are built with their own tasks. */
const BUILT_STEPS: readonly string[] = ['organisation', 'location', 'service'];

/**
 * The values one step sends, or null when a code is not one the back end holds. The invitation's
 * values (the organisation name and ODS code, the service name) are read from the back end here,
 * never taken from the browser.
 */
async function valuesFor(step: StepName, body: Record<string, unknown>, token: string, id: string): Promise<Record<string, unknown> | null> {
  if (step === 'location') return locationValues(body);
  const registration = await readRegistration(token, id);
  if (step === 'service') return serviceValues(body, registration.invitation.serviceName);
  return organisationValues(body, {
    organisationName: registration.invitation.organisationName,
    odsCode: registration.invitation.odsCode,
  });
}

const put = withBff<Context>(
  async (request, session, context) => {
    const { id, step } = await context.params;
    if (!ID.test(id) || !isStepName(step) || !BUILT_STEPS.includes(step)) {
      return refuse(404, 'not-found', 'We could not find that.');
    }
    const body = await jsonBody(request, STEP_FIELDS[step]);
    if (body === null) return refuse(400, 'invalid', 'The request was not valid.');

    const values = await valuesFor(step, body, session.backendToken, id);
    if (values === null) return refuse(400, 'invalid', 'The request was not valid.');

    try {
      const saved = await saveStep(session.backendToken, id, step, values);
      return bffJson(200, { status: saved.status });
    } catch (error) {
      if (error instanceof FhirError && error.status === 400) {
        return bffJson(422, { errors: issuesFromOutcome(error.outcome) });
      }
      throw error;
    }
  },
  { roles: ['reporter'] },
);

export async function PUT(request: Request, context: Context): Promise<Response> {
  return put(request, context);
}
