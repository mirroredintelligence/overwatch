import { withBff } from '@/lib/bff/handler';
import { readRegistration } from '@/lib/register/backend';
import { reviewRowsFrom } from '@/lib/register/applicant';
import { bffJson, refuse } from '@/lib/register/requests';

// The review of a registration (W26): one row per answered step, complete or needing attention, with
// the words the back end gives. The rows come from the record; nothing else the back end holds leaves.

type Context = { params: Promise<{ id: string }> };

const ID = /^[A-Za-z0-9-]{1,64}$/;

const get = withBff<Context>(
  async (_request, session, context) => {
    const { id } = await context.params;
    if (!ID.test(id)) return refuse(404, 'not-found', 'We could not find that.');
    const view = await readRegistration(session.backendToken, id);
    return bffJson(200, { sections: reviewRowsFrom(view) });
  },
  { idScoped: true, roles: ['reporter'] },
);

export async function GET(request: Request, context: Context): Promise<Response> {
  return get(request, context);
}
