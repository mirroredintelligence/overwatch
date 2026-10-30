import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { fakeBackendToken } from '@/test/backendToken';
import { BACKEND_ROOT } from '@/test/fixtures/links';
import { tenantForHost } from '@/test/tenants';

// The back end's token exchange as the front end sees it (TEN-043): `POST /auth/token` with
// `{"idToken"}`. The tenant is the request HOST and nothing else; the directory the identity token
// names must be the one that tenant has bound; the role comes from the tenant's own mapping (here the
// app roles of the sample identity); every refusal is the one 403 body; a host nobody owns is a 404.
// A stand-in: it reads the identity token's claims without checking a signature, because the real
// back end verifies it against the directory's keys and the front end never does this itself.

export const EXCHANGE_URL = `${BACKEND_ROOT}/auth/token`;

export type SeenExchange = { host: string | null; body: unknown; authorization: string | null };
/** Every exchange the back end stand-in saw, newest last. */
export const seenExchanges: SeenExchange[] = [];

export function resetExchanges() {
  seenExchanges.length = 0;
}

const ROLE_FOR_APP_ROLE: Record<string, string> = {
  'DIUCS.Lead': 'lead',
  'DIUCS.Clinical': 'clinical',
  'DIUCS.Advisor': 'advisor',
  'DIUCS.Owner': 'owner',
  'DIUCS.Planning': 'exec',
};
const PRIORITY = ['lead', 'clinical', 'advisor', 'owner', 'exec'];

export const FORBIDDEN_BODY = { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'forbidden', diagnostics: 'Your account does not have access.' }] };
const NOT_FOUND_BODY = { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'not-found' }] };

function claimsOfIdentity(idToken: string): Record<string, unknown> {
  try {
    return JSON.parse(Buffer.from(idToken.split('.')[1] ?? '', 'base64url').toString('utf8')) as Record<string, unknown>;
  } catch {
    return {};
  }
}

const exchange: HttpResponseResolver = async ({ request }) => {
  const host = request.headers.get('host');
  const body = (await request.json().catch(() => null)) as unknown;
  seenExchanges.push({ host, body, authorization: request.headers.get('authorization') });

  const tenant = tenantForHost(host);
  if (!tenant) return HttpResponse.json(NOT_FOUND_BODY, { status: 404 });
  const keys = typeof body === 'object' && body !== null ? Object.keys(body) : [];
  const idToken = (body as { idToken?: unknown } | null)?.idToken;
  if (keys.length !== 1 || typeof idToken !== 'string') return HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'invalid' }] }, { status: 400 });

  const claims = claimsOfIdentity(idToken);
  const roles = Array.isArray(claims.roles) ? claims.roles.map(String) : [];
  const given = new Set(roles.map((r) => ROLE_FOR_APP_ROLE[r]).filter((r): r is string => r !== undefined));
  const role = PRIORITY.find((candidate) => given.has(candidate));
  const directory = typeof claims.tid === 'string' ? claims.tid.toLowerCase() : '';
  if (tenant.directoryId === null || directory !== tenant.directoryId || role === undefined) {
    return HttpResponse.json(FORBIDDEN_BODY, { status: 403, headers: { 'Cache-Control': 'no-store' } });
  }

  const now = new Date();
  const expires = Math.floor(now.getTime() / 1000) + 8 * 3600;
  const subject = `stf-${tenant.id}-${String(claims.oid ?? '').slice(0, 8)}`.padEnd(36, '0').slice(0, 36);
  const token = fakeBackendToken({ sub: subject, role, tenant: tenant.id, exp: expires }, now);
  return HttpResponse.json(
    { token, expiresAt: new Date(expires * 1000).toISOString().replace('.000Z', 'Z'), role },
    { headers: { 'Cache-Control': 'no-store' } },
  );
};

export const authHandlers = [http.post(EXCHANGE_URL, exchange)];
