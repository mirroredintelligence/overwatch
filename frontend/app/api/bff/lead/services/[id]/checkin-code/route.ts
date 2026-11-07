import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { routeId } from '@/lib/lead/bffInput';
import { parseCheckinCode } from '@/lib/lead/checkin';

// Makes the code a service prints and pins up (DEC-1346). Lead only, with CSRF. Making one stops the last, so it is a
// press and never a read. The back end answers the page address and the QR matrix; the shape is checked before it is
// passed on, and the answer is never cached.

type Context = { params: Promise<Record<string, string>> };

const post = withBff<Context>(
  async (_request, session, context) => {
    const id = await routeId(context, 'id');
    const { data } = await fhirFetch<unknown>(`/lead/services/${encodeURIComponent(id)}/checkin-code`, {
      method: 'POST',
      root: true,
      token: session.backendToken,
      body: {},
    });
    return Response.json(parseCheckinCode(data), { headers: { 'Cache-Control': 'no-store' } });
  },
  { idScoped: true, roles: ['lead'] },
);

export const POST = (request: Request, context: Context) => post(request, context);
