import { withBff } from '@/lib/bff/handler';
import { fhirFetch, FhirError } from '@/lib/fhir/client';
import { idempotencyKeyOf, invalidRequest, jsonBody, routeId } from '@/lib/lead/bffInput';
import { type CoverageInput, coverageWire, DAYS, MAX_RESPONSE_HOURS, parseCoverageForm } from '@/lib/areas/types';
import { DISTRICT_PATTERN } from '@/lib/advisor/options';

// A service's coverage area, read and saved by the shift lead (RadarWeb 5): the postcode districts it
// visits, its response target in hours, and the days it visits. The back end's route IS NOT BUILT YET (the
// contract is in lib/areas/types.ts): until it is, the back end answers 404 and so does this route. The
// service is the address; the body names nothing else (no tenant, no organisation). Lead only.

type Context = { params: Promise<Record<string, string>> };

function unreadable(): FhirError {
  return new FhirError(502, {
    resourceType: 'OperationOutcome',
    issue: [{ severity: 'error', code: 'exception', diagnostics: 'The back end returned an unreadable coverage area.' }],
  });
}

/** The save as the form sends it, checked by shape: districts, whole hours, days. Anything else is null. */
function inputOf(body: unknown): CoverageInput | null {
  if (typeof body !== 'object' || body === null) return null;
  const source = body as { districts?: unknown; responseHours?: unknown; days?: unknown };
  const { districts, responseHours, days } = source;
  if (!Array.isArray(districts) || districts.length === 0 || districts.length > 60) return null;
  if (!districts.every((item) => typeof item === 'string' && DISTRICT_PATTERN.test(item))) return null;
  if (typeof responseHours !== 'number' || !Number.isInteger(responseHours) || responseHours < 1 || responseHours > MAX_RESPONSE_HOURS) return null;
  if (!Array.isArray(days) || days.length === 0 || !days.every((day) => DAYS.some((known) => known.value === day))) return null;
  return {
    districts: [...new Set(districts as string[])],
    responseHours,
    days: [...new Set(days as CoverageInput['days'])],
  };
}

const get = withBff<Context>(
  async (_request, session, context) => {
    const id = await routeId(context, 'id');
    const { data } = await fhirFetch<unknown>(`/lead/services/${encodeURIComponent(id)}/coverage`, {
      root: true,
      token: session.backendToken,
      cache: 'no-store',
    });
    const form = parseCoverageForm(data);
    if (form === null) throw unreadable();
    return Response.json(coverageWire(form), { headers: { 'Cache-Control': 'no-store' } });
  },
  { idScoped: true, roles: ['lead'] },
);

const put = withBff<Context>(
  async (request, session, context) => {
    const id = await routeId(context, 'id');
    const key = idempotencyKeyOf(request);
    const input = inputOf(await jsonBody(request));
    if (input === null) throw invalidRequest();
    const { data } = await fhirFetch<unknown>(`/lead/services/${encodeURIComponent(id)}/coverage`, {
      root: true,
      method: 'PUT',
      body: input,
      token: session.backendToken,
      idempotencyKey: key,
    });
    const form = parseCoverageForm(data);
    if (form === null) throw unreadable();
    return Response.json(coverageWire(form), { headers: { 'Cache-Control': 'no-store' } });
  },
  { idScoped: true, roles: ['lead'] },
);

export const GET = (request: Request, context: Context) => get(request, context);
export const PUT = (request: Request, context: Context) => put(request, context);
