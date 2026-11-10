import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { idempotencyKeyOf, routeId } from '@/lib/lead/bffInput';
import { parametersOf, partValue } from '@/lib/lead/parameters';

// Retires a service (DEC-1356): the back end's $retire. The service is made inactive and leaves every list of
// active services; nothing is deleted. Lead only, CSRF, and the Idempotency-Key is passed on. The answer says how
// many open requests it expired.

type Context = { params: Promise<Record<string, string>> };

const post = withBff<Context>(
  async (request, session, context) => {
    const id = await routeId(context, 'id');
    const key = idempotencyKeyOf(request);
    const { data } = await fhirFetch<unknown>(`/HealthcareService/${encodeURIComponent(id)}/$retire`, {
      method: 'POST',
      body: parametersOf([]),
      token: session.backendToken,
      idempotencyKey: key,
    });
    const expired = partValue(data, 'expiredRequests');
    return Response.json(
      { expiredRequests: typeof expired === 'number' ? expired : 0 },
      { headers: { 'Cache-Control': 'no-store' } },
    );
  },
  { idScoped: true, roles: ['lead'] },
);

export const POST = (request: Request, context: Context) => post(request, context);
