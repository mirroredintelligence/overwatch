import { withBff } from '@/lib/bff/handler';
import { sendTestNotification } from '@/lib/register/backend';
import { bffJson, refuse } from '@/lib/register/requests';

// One of the applicant's actions on the status page (W27). The browser sends CSRF with it (a POST).

type Context = { params: Promise<{ id: string }> };

const ID = /^[A-Za-z0-9-]{1,64}$/;

const post = withBff<Context>(
  async (_request, session, context) => {
    const { id } = await context.params;
    if (!ID.test(id)) return refuse(404, 'not-found', 'We could not find that.');
    await sendTestNotification(session.backendToken, id);
    return bffJson(200, { done: true });
  },
  { roles: ['reporter'] },
);

export async function POST(request: Request, context: Context): Promise<Response> {
  return post(request, context);
}
