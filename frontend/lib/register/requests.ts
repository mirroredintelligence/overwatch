// Shared request helpers for the registration BFF routes. The browser sends JSON only, which a
// cross-site form cannot do without a preflight the BFF never grants, and a body may carry only the
// fields the route names: anything else (a tenant, a role, a host) is refused, never read.

export const NO_STORE = { 'Cache-Control': 'no-store' } as const;

export function bffJson(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return Response.json(body, { status, headers: { ...NO_STORE, ...headers } });
}

export function refuse(status: number, code: string, message: string, headers: Record<string, string> = {}): Response {
  return bffJson(status, { code, message }, headers);
}

/**
 * The body as an object whose keys are all in `fields`, or null: not JSON, not an object, not
 * `application/json`, or a key the route does not name.
 */
export async function jsonBody(request: Request, fields: readonly string[]): Promise<Record<string, unknown> | null> {
  const type = request.headers.get('content-type') ?? '';
  if (!type.toLowerCase().startsWith('application/json')) return null;
  let parsed: unknown;
  try {
    parsed = await request.json();
  } catch {
    return null;
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return null;
  const body = parsed as Record<string, unknown>;
  if (Object.keys(body).some((key) => !fields.includes(key))) return null;
  return body;
}
