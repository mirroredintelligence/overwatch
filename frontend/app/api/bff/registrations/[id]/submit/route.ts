import { FhirError } from '@/lib/fhir/client';
import { withBff } from '@/lib/bff/handler';
import { submitRegistration } from '@/lib/register/backend';
import { issuesFromOutcome } from '@/lib/register/draft';
import { bffJson, refuse } from '@/lib/register/requests';

// Submit for approval (W26): the back end's $submit, with the reporter's token. The CSRF check is the
// BFF's own (a POST). A refusal comes back as the errors the review shows, never as the back end's text.

type Context = { params: Promise<{ id: string }> };

const ID = /^[A-Za-z0-9-]{1,64}$/;

const post = withBff<Context>(
  async (_request, session, context) => {
    const { id } = await context.params;
    if (!ID.test(id)) return refuse(404, 'not-found', 'We could not find that.');
    try {
      const result = await submitRegistration(session.backendToken, id);
      return bffJson(200, { status: result.status });
    } catch (error) {
      if (error instanceof FhirError && error.status === 400) {
        return bffJson(422, { errors: issuesFromOutcome(error.outcome) });
      }
      throw error;
    }
  },
  { roles: ['reporter'] },
);

export async function POST(request: Request, context: Context): Promise<Response> {
  return post(request, context);
}
