import { withBff } from '@/lib/bff/handler';
import { readHistory } from '@/lib/criteria/backend';
import { idOf } from '@/lib/registration/request';

// The version history of one service (W31): every version, newest first, with its status and review
// date. The criteria id stays on the server. Owner, clinical lead and shift lead may read it (U30).

type Context = { params: Promise<{ serviceId: string }> };
const NO_STORE = { 'Cache-Control': 'no-store' };

const get = withBff<Context>(
  async (_request, session, context) => {
    const serviceId = idOf((await context.params).serviceId);
    const versions = await readHistory(session.backendToken, serviceId);
    return Response.json(
      { versions: versions.map(({ version, status, reviewBy }) => ({ version, status, reviewBy })) },
      { headers: NO_STORE },
    );
  },
  { idScoped: true, roles: ['owner', 'clinical', 'lead'] },
);

export const GET = (request: Request, context: Context) => get(request, context);
