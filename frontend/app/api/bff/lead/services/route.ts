import { withBff } from '@/lib/bff/handler';
import { fhirFetch } from '@/lib/fhir/client';
import { idempotencyKeyOf, jsonBody } from '@/lib/lead/bffInput';
import { readServiceBody, toParameters } from '@/lib/lead/serviceBody';

// The services the shift lead may choose from (GET), and the add-a-service form's save (POST), which the
// back end's $setup takes (R08, DEC-652). Lead only; CSRF on the POST (withBff). The answer names the new
// service and nothing else: no reporter number, no criteria (H-331).

const NO_STORE = { 'Cache-Control': 'no-store' };

type Bundle = { entry?: { resource?: Record<string, unknown> }[] };

function servicesFrom(bundle: Bundle): { id: string; name: string }[] {
  const services: { id: string; name: string }[] = [];
  for (const entry of bundle.entry ?? []) {
    const resource = entry.resource;
    if (resource?.resourceType !== 'HealthcareService' || resource.active === false) continue;
    if (typeof resource.id === 'string' && typeof resource.name === 'string') {
      services.push({ id: resource.id, name: resource.name });
    }
  }
  return services;
}

const get = withBff(
  async (_request, session) => {
    const { data } = await fhirFetch<Bundle>('/HealthcareService?_count=200', { token: session.backendToken });
    return Response.json({ services: servicesFrom(data) }, { headers: NO_STORE });
  },
  { roles: ['lead'] },
);

const post = withBff(
  async (request, session) => {
    const key = idempotencyKeyOf(request);
    const body = readServiceBody(await jsonBody(request));
    const { data } = await fhirFetch<{ id?: unknown }>('/HealthcareService/$setup', {
      method: 'POST',
      body: toParameters(body),
      token: session.backendToken,
      idempotencyKey: key,
    });
    const serviceId = typeof data?.id === 'string' ? data.id : undefined;
    if (serviceId === undefined) throw new Error('the back end did not name the new service');
    return Response.json({ serviceId }, { status: 201, headers: NO_STORE });
  },
  { roles: ['lead'] },
);

export const GET = (request: Request) => get(request, undefined);
export const POST = (request: Request) => post(request, undefined);
