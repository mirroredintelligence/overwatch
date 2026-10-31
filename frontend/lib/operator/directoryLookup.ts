// Looks up an organisation's Entra directory (tenant) id from its domain, for the create-tenant form. The public
// OpenID configuration of a domain names its tenant and needs no sign-in, no permission and no consent (tested
// against the platform's own domain). Nothing else about the directory is read: group ids and consent state
// can only be read from inside the organisation's own tenant, so they are not looked up here.
//
// Only this one host is called, with a domain that passes the strict pattern below, and only the issuer of its
// answer is used. A redirect, a slow answer, or an answer that is not a tenant id gives no id (never a guess).

const DOMAIN = /^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/;
const ISSUER = /^https:\/\/login\.microsoftonline\.com\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\/v2\.0$/i;
const TIMEOUT_MS = 5_000;

/** The domain as the lookup takes it (lower case, trimmed), or null when it is not a domain name. */
export function normaliseLookupDomain(input: string): string | null {
  const domain = input.trim().toLowerCase().replace(/\.$/, '');
  return DOMAIN.test(domain) ? domain : null;
}

/** The tenant id of an issuer address (`https://login.microsoftonline.com/<id>/v2.0`), or null. */
export function directoryIdFromIssuer(issuer: unknown): string | null {
  if (typeof issuer !== 'string') return null;
  return ISSUER.exec(issuer)?.[1]?.toLowerCase() ?? null;
}

/** The directory id of a domain, or null when it has none, cannot be reached in time, or answers oddly. */
export async function lookupDirectoryId(domain: string, fetcher: typeof fetch = fetch): Promise<string | null> {
  const clean = normaliseLookupDomain(domain);
  if (clean === null) return null;
  try {
    const response = await fetcher(`https://login.microsoftonline.com/${clean}/v2.0/.well-known/openid-configuration`, {
      redirect: 'error',
      signal: AbortSignal.timeout(TIMEOUT_MS),
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) return null;
    const body = (await response.json()) as { issuer?: unknown };
    return directoryIdFromIssuer(body.issuer);
  } catch {
    return null;
  }
}
