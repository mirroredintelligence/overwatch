// The names a caller must never use to choose a tenant, a scope or a network (DEC-130 item 3,
// DEC-132). The BFF refuses a request that carries one (lib/bff/inputGuard.ts) and the back-end
// client refuses to send one (lib/fhir/client.ts), so the tenant of a call is the session's token and
// nothing else. Names are compared without case, dashes, underscores, dots, brackets or spaces, so
// `tenant_id`, `Tenant-Id`, `tenant.id` and `tenant[id]` are one name.

const SEPARATORS = /[-_.[\]\s]/g;

export function normaliseName(name: string): string {
  return name.toLowerCase().replace(SEPARATORS, '');
}

/** True for a key that chooses a tenant, a scope or a network. */
export function namesTenantInput(name: string): boolean {
  const key = normaliseName(name);
  return (
    key === 'source' ||
    key.startsWith('tenant') ||
    key.startsWith('scope') ||
    key.startsWith('network') ||
    key.startsWith('sourcetenant')
  );
}
