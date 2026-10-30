import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { claimsOf } from '@/test/backendToken';
import { recordsFor } from '@/test/tenants';
import { BACKEND_BASE } from './board';

// A stand-in for the back end's records, tenant-aware like the real one (TEN-047): the tenant is the
// `tenant` claim of the bearer token and nothing else, a record that is in another tenant is a 404
// exactly like a record that is nowhere (DEC-130 item 7), and a token it cannot read is a 401. Tenant
// A and tenant B hold the same identifiers with different content (test/tenants.ts), so a route that
// forgets the tenant returns the wrong record, not a 404.
//
// Routes: GET /fhir/HealthcareService/{id} and GET /fhir/ServiceRequest/{reference}.

const NOT_FOUND = { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'not-found' }] };
const LOGIN = { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'login' }] };

function tenantOf(request: Request): string | null {
  const header = request.headers.get('authorization');
  const token = header === null ? undefined : /^Bearer (.+)$/.exec(header)?.[1];
  if (token === undefined || token.split('.').length !== 3) return null;
  try {
    const tenant = claimsOf(token).tenant;
    return typeof tenant === 'string' ? tenant : null;
  } catch {
    return null;
  }
}

const service: HttpResponseResolver = ({ request, params }) => {
  const tenant = tenantOf(request);
  if (tenant === null) return HttpResponse.json(LOGIN, { status: 401 });
  const found = recordsFor(tenant)?.services.find((s) => s.id === String(params.id));
  if (!found) return HttpResponse.json(NOT_FOUND, { status: 404 });
  return HttpResponse.json({ resourceType: 'HealthcareService', id: found.id, name: found.name });
};

const serviceRequest: HttpResponseResolver = ({ request, params }) => {
  const tenant = tenantOf(request);
  if (tenant === null) return HttpResponse.json(LOGIN, { status: 401 });
  const found = recordsFor(tenant)?.cases.find((c) => c.reference === String(params.reference));
  if (!found) return HttpResponse.json(NOT_FOUND, { status: 404 });
  return HttpResponse.json({ resourceType: 'ServiceRequest', id: found.reference, note: found.note });
};

export const tenantDataHandlers = [
  http.get(`${BACKEND_BASE}/HealthcareService/:id`, service),
  http.get(`${BACKEND_BASE}/ServiceRequest/:reference`, serviceRequest),
];
