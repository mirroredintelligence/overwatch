// The two identifier shapes the sign-in and the session check: a directory or object id (a GUID, as
// Entra writes them) and a tenant id as the back end accepts it (application/tenancy.py
// TENANT_ID_PATTERN). A network id (`net-...`) is never a tenant id: a session is for one tenant.

const GUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const TENANT_ID = /^[a-z0-9][a-z0-9-]{1,30}$/;

export function isTenantId(value: unknown): value is string {
  return typeof value === 'string' && TENANT_ID.test(value) && !value.startsWith('net-');
}

export function isGuid(value: unknown): value is string {
  return typeof value === 'string' && GUID.test(value);
}
