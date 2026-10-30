import { withBff } from '@/lib/bff/handler';
import { idOf } from '@/lib/registration/request';
import { sendTestNotification } from '@/lib/register/backend';
import { bffJson, refuse } from '@/lib/register/requests';

// Two callers share this path: the applicant sends the test notification from the status page (W27); a
// lead sends it again at go live (W29). The back end allows both. It answers 409 inside a minute.

type Context = { params: Promise<{ id: string }> };

const ID = /^[A-Za-z0-9-]{1,64}$/;

const post = withBff<Context>(
  async (_request, session, context) => {
    const { id } = await context.params;
    if (session.role === 'lead') idOf(id);
    if (!ID.test(id)) return refuse(404, 'not-found', 'We could not find that.');
    await sendTestNotification(session.backendToken, id);
    return bffJson(200, { done: true });
  },
  { idScoped: true, roles: ['reporter', 'lead'] },
);

export async function POST(request: Request, context: Context): Promise<Response> {
  return post(request, context);
}
