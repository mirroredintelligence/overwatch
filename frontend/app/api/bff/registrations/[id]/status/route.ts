import { withBff } from '@/lib/bff/handler';
import { readStatus } from '@/lib/register/backend';
import { statusFrom } from '@/lib/register/applicant';
import { bffJson, refuse } from '@/lib/register/requests';

// The applicant's status after submitting (W27). The BFF passes on the fields the page shows, mapped
// by statusFrom, and nothing else the back end holds about the registration.

type Context = { params: Promise<{ id: string }> };

const ID = /^[A-Za-z0-9-]{1,64}$/;

const get = withBff<Context>(
  async (_request, session, context) => {
    const { id } = await context.params;
    if (!ID.test(id)) return refuse(404, 'not-found', 'We could not find that.');
    const view = statusFrom(await readStatus(session.backendToken, id));
    if (view === null) return refuse(503, 'unavailable', 'We could not load your registration. Try again later.');
    return bffJson(200, view);
  },
  { idScoped: true, roles: ['reporter'] },
);

export async function GET(request: Request, context: Context): Promise<Response> {
  return get(request, context);
}
