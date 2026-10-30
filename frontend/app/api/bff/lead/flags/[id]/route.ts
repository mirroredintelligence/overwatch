import { withBff } from '@/lib/bff/handler';
import { backendFetch } from '@/lib/fhir/client';
import { idempotencyKeyOf, invalidRequest, jsonBody, routeId } from '@/lib/lead/bffInput';
import { parametersOf, partValue } from '@/lib/lead/parameters';

// Resolves one flag (W42): "accept" is the accepted outcome and "checked" the checked one (U39). A suspension
// is a service action, made with the suspend route, so "suspend" is refused here.

type Context = { params: Promise<Record<string, string>> };

const OUTCOMES: Record<string, string> = { accept: 'accepted', checked: 'checked' };

const post = withBff<Context>(
  async (request, session, context) => {
    const id = await routeId(context, 'id');
    const key = idempotencyKeyOf(request);
    const body = (await jsonBody(request)) as { action?: unknown } | null;
    const outcome = typeof body?.action === 'string' ? OUTCOMES[body.action] : undefined;
    if (outcome === undefined || !Object.hasOwn(OUTCOMES, body?.action as string)) throw invalidRequest();

    const { data } = await backendFetch<unknown>(`/admin/report-flags/${encodeURIComponent(id)}/$resolve`, {
      method: 'POST',
      body: parametersOf([{ name: 'outcome', valueString: outcome }]),
      token: session.backendToken,
      idempotencyKey: key,
    });
    const flagId = partValue(data, 'flagId');
    const answered = partValue(data, 'outcome');
    return Response.json(
      { flagId: typeof flagId === 'string' ? flagId : id, outcome: typeof answered === 'string' ? answered : outcome },
      { headers: { 'Cache-Control': 'no-store' } },
    );
  },
  { roles: ['lead'] },
);

export const POST = (request: Request, context: Context) => post(request, context);
