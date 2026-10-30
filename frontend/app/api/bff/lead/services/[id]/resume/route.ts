import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { idempotencyKeyOf, invalidRequest, jsonBody, routeId } from '@/lib/lead/bffInput';
import { parametersOf, partValue } from '@/lib/lead/parameters';

// Resumes a service (W42): the back end's $resume, which needs both confirmations true (U36). Lead only, CSRF.

type Context = { params: Promise<Record<string, string>> };

const post = withBff<Context>(
  async (request, session, context) => {
    const id = await routeId(context, 'id');
    const key = idempotencyKeyOf(request);
    const body = (await jsonBody(request)) as { phonedRegisterNumber?: unknown; reasonResolved?: unknown } | null;
    if (body?.phonedRegisterNumber !== true || body?.reasonResolved !== true) throw invalidRequest();

    const { data } = await fhirFetch<unknown>(`/HealthcareService/${encodeURIComponent(id)}/$resume`, {
      method: 'POST',
      body: parametersOf([
        { name: 'calledBack', valueBoolean: true },
        { name: 'reasonResolved', valueBoolean: true },
      ]),
      token: session.backendToken,
      idempotencyKey: key,
    });
    const status = partValue(data, 'status');
    const nextDueAt = partValue(data, 'nextDueAt');
    return Response.json(
      { status: typeof status === 'string' ? status : null, nextDueAt: typeof nextDueAt === 'string' ? nextDueAt : null },
      { headers: { 'Cache-Control': 'no-store' } },
    );
  },
  { idScoped: true, roles: ['lead'] },
);

export const POST = (request: Request, context: Context) => post(request, context);
