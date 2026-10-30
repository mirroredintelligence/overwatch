import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { BACKEND_ROOT } from '@/test/fixtures/links';
import { tenantForHost } from '@/test/tenants';

// The back end's public tenant profile (TEN-040): no token, the tenant is the Host header, and a host
// no tenant owns answers as a path that is not there. Every request is kept, with the Host it was
// sent to and every header name, so a test can show what the front end sent.

export const PROFILE_URL = `${BACKEND_ROOT}/public/tenant-profile`;

export type SeenProfileRequest = { host: string | null; headerNames: string[] };
export const seenProfileRequests: SeenProfileRequest[] = [];

export function resetProfileRequests() {
  seenProfileRequests.length = 0;
}

const profile: HttpResponseResolver = ({ request }) => {
  const host = request.headers.get('host');
  seenProfileRequests.push({ host, headerNames: [...request.headers.keys()] });
  const tenant = tenantForHost(host);
  if (!tenant || tenant.profile === null) {
    return HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'not-found' }] }, { status: 404, headers: { 'Cache-Control': 'no-store' } });
  }
  return HttpResponse.json(tenant.profile, { headers: { 'Cache-Control': 'no-store', Vary: 'Host' } });
};

export const profileHandlers = [http.get(PROFILE_URL, profile)];
