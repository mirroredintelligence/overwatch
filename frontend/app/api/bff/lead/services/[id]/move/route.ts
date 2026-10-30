import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { idempotencyKeyOf, invalidRequest, jsonBody, routeId } from '@/lib/lead/bffInput';
import { isUkMobile } from '@/lib/forms/ukMobile';
import { endOfLondonDay } from '@/lib/lead/londonDay';
import { parametersOf, partValue, type ParameterValue } from '@/lib/lead/parameters';

// Moves a service to another phone (W43): the back end's $move (U38). Lead only, CSRF. "changed" is until the
// lead changes it; "date" is the end of that London day (DEC-654).

type Context = { params: Promise<Record<string, string>> };

const post = withBff<Context>(
  async (request, session, context) => {
    const id = await routeId(context, 'id');
    const key = idempotencyKeyOf(request);
    const body = (await jsonBody(request)) as { toPhone?: unknown; until?: unknown; date?: unknown } | null;
    if (typeof body?.toPhone !== 'string' || !isUkMobile(body.toPhone)) throw invalidRequest();

    const parts: ParameterValue[] = [{ name: 'toMobile', valueString: body.toPhone }];
    if (body.until === 'date') {
      if (typeof body.date !== 'string') throw invalidRequest();
      let until: string;
      try {
        until = endOfLondonDay(body.date);
      } catch {
        throw invalidRequest();
      }
      parts.push({ name: 'until', valueDateTime: until });
    } else if (body.until !== 'changed') {
      throw invalidRequest();
    }

    const { data } = await fhirFetch<unknown>(`/HealthcareService/${encodeURIComponent(id)}/$move`, {
      method: 'POST',
      body: parametersOf(parts),
      token: session.backendToken,
      idempotencyKey: key,
    });
    const moveId = partValue(data, 'moveId');
    return Response.json(
      { moveId: typeof moveId === 'string' ? moveId : null },
      { status: 201, headers: { 'Cache-Control': 'no-store' } },
    );
  },
  { roles: ['lead'] },
);

export const POST = (request: Request, context: Context) => post(request, context);
