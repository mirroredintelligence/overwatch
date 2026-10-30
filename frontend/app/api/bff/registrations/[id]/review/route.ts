import { withBff } from '@/lib/bff/handler';
import { readReview } from '@/lib/register/backend';
import { bffJson, refuse } from '@/lib/register/requests';

// The review of a registration (W26): one row per section, complete or needing attention, with the
// words the back end gives. Nothing else the back end holds leaves the BFF.

type Context = { params: Promise<{ id: string }> };

const ID = /^[A-Za-z0-9-]{1,64}$/;
const STATUSES = ['complete', 'needs-attention'];

const get = withBff<Context>(
  async (_request, session, context) => {
    const { id } = await context.params;
    if (!ID.test(id)) return refuse(404, 'not-found', 'We could not find that.');
    const rows = await readReview(session.backendToken, id);
    return bffJson(200, {
      sections: rows
        .filter((row) => STATUSES.includes(row.status))
        .map((row) => ({ key: row.key, status: row.status, summary: row.summary })),
    });
  },
  { roles: ['reporter'] },
);

export async function GET(request: Request, context: Context): Promise<Response> {
  return get(request, context);
}
