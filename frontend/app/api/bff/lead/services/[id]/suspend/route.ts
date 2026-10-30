import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { idempotencyKeyOf, jsonBody, invalidRequest, routeId } from '@/lib/lead/bffInput';
import { parametersOf, partValue } from '@/lib/lead/parameters';

// Suspends a service (W42): the back end's $suspend, with the reason as a code (U36). Lead only, CSRF, and
// the Idempotency-Key is passed on. The answer gives the time the back end took the suspension, how many open
// requests it expired, and whether the service was told by text (DEC-657).

type Context = { params: Promise<Record<string, string>> };

const REASONS = ['suspected-false-reports', 'closed-unexpectedly', 'contact-unreachable', 'other'] as const;

const post = withBff<Context>(
  async (request, session, context) => {
    const id = await routeId(context, 'id');
    const key = idempotencyKeyOf(request);
    const body = (await jsonBody(request)) as { reason?: unknown } | null;
    const reason = REASONS.find((r) => r === body?.reason);
    if (reason === undefined) throw invalidRequest();

    const { data } = await fhirFetch<unknown>(`/HealthcareService/${encodeURIComponent(id)}/$suspend`, {
      method: 'POST',
      body: parametersOf([{ name: 'reason', valueCode: reason }]),
      token: session.backendToken,
      idempotencyKey: key,
    });
    const expired = partValue(data, 'expiredRequests');
    const notified = partValue(data, 'notified');
    return Response.json(
      {
        since: new Date().toISOString(),
        expiredRequests: typeof expired === 'number' ? expired : 0,
        notified: notified === true,
      },
      { headers: { 'Cache-Control': 'no-store' } },
    );
  },
  { roles: ['lead'] },
);

export const POST = (request: Request, context: Context) => post(request, context);
