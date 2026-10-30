import { withBff } from '@/lib/bff/handler';
import { routeId } from '@/lib/lead/bffInput';
import { fetchReplay } from '@/lib/lead/auditServer';

// The audit replay of one case or booking reference (W47): what the advisor saw at the decision. Lead only.
// Not cached (no-store on the answer and on the back-end call). The back end audits the read itself.

type Context = { params: Promise<Record<string, string>> };

const get = withBff<Context>(
  async (_request, session, context) => {
    const reference = await routeId(context, 'ref');
    const replay = await fetchReplay(session.backendToken, reference);
    return Response.json(replay, { headers: { 'Cache-Control': 'no-store' } });
  },
  { idScoped: true, roles: ['lead'] },
);

export const GET = (request: Request, context: Context) => get(request, context);
