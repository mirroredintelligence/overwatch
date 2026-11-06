import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { routeId } from '@/lib/lead/bffInput';

// Takes a duty manager off a service's roster for good (DEC-1341). Lead only, CSRF checked (a POST, so the browser
// sends the token like every other write). The back end's route is a DELETE; the answer is a fixed one.

type Context = { params: Promise<Record<string, string>> };

const post = withBff<Context>(
  async (_request, session, context) => {
    const id = await routeId(context, 'id');
    await fhirFetch<unknown>(`/lead/roster/${encodeURIComponent(id)}`, {
      method: 'DELETE',
      root: true,
      token: session.backendToken,
    });
    return Response.json({ removed: true }, { headers: { 'Cache-Control': 'no-store' } });
  },
  { idScoped: true, roles: ['lead'] },
);

export const POST = (request: Request, context: Context) => post(request, context);
