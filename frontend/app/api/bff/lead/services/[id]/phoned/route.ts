import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { idempotencyKeyOf, jsonBody, routeId } from '@/lib/lead/bffInput';
import { phonedPayload, readPhonedBody } from '@/lib/lead/phonedBody';

// "Enter what they told me by phone" (W17, W42, W43): the shift lead records what a service said on the phone,
// with no case (DEC-920). Lead only, CSRF on the POST, the Idempotency-Key is passed on so a double press records
// once. The advisor's phoned answer on a case is a different route and is not open to the lead here.

type Context = { params: Promise<Record<string, string>> };

const post = withBff<Context>(
  async (request, session, context) => {
    const id = await routeId(context, 'id');
    const key = idempotencyKeyOf(request);
    const input = readPhonedBody(await jsonBody(request));
    const { data } = await fhirFetch<{ value?: unknown }>(`/lead/services/${encodeURIComponent(id)}/phoned`, {
      method: 'POST',
      root: true,
      body: phonedPayload(input),
      token: session.backendToken,
      idempotencyKey: key,
    });
    const value = typeof data.value === 'number' ? data.value : null;
    return Response.json({ recorded: true, value }, { status: 201, headers: { 'Cache-Control': 'no-store' } });
  },
  { idScoped: true, roles: ['lead'] },
);

export const POST = (request: Request, context: Context) => post(request, context);
