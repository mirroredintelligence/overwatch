import type { Role, Session } from '@/lib/auth/session';
import { fhirFetch, type FhirInit, type FhirResult } from '@/lib/fhir/client';

// Server-only. The console's calls to the back end's support routes, which sit at the back end's
// root (R18). The token is the one the sealed session holds: it says who is asking, and no tenant,
// organisation or support scope is taken from the caller (DEC-130, DEC-132).

export const CONSOLE_ROLES: readonly Role[] = ['support'];

// What the console's own path segments may hold. A session id is one the back end issued; a trace
// id is 32 lower-case hex characters, as W3C defines it. Anything else never reaches the back end.
export const SESSION_ID_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;
export const TRACE_ID_PATTERN = /^[a-f0-9]{32}$/;

export type ConsoleInit = Omit<FhirInit, 'token' | 'root'>;

export function consoleCall<T>(
  session: Pick<Session, 'backendToken'>,
  path: string,
  init: ConsoleInit = {},
): Promise<FhirResult<T>> {
  return fhirFetch<T>(path, { ...init, root: true, token: session.backendToken });
}

const MAX_BODY_CHARS = 4096;
export const NO_STORE = { 'Cache-Control': 'no-store' };

/** A request's JSON object, or null when the body is missing, too long or not an object. */
export async function jsonBody(request: Request): Promise<Record<string, unknown> | null> {
  const text = await request.text();
  if (text.length > MAX_BODY_CHARS) return null;
  try {
    const parsed: unknown = JSON.parse(text);
    return typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

/** A short text field of a body: 1 to 32 characters, or undefined. Nothing else is read from it. */
export function shortText(body: Record<string, unknown>, key: string): string | undefined {
  const value = body[key];
  return typeof value === 'string' && value.length >= 1 && value.length <= 32 ? value : undefined;
}

/** A session id from a route segment, or null when it cannot be one the back end issued. */
export function sessionIdOf(value: string): string | null {
  return SESSION_ID_PATTERN.test(value) ? value : null;
}
