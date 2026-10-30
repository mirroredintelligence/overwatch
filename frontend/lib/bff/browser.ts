import { withTraceparent } from '@/lib/telemetry/trace';

// The browser's calls to the BFF's JSON routes. The CSRF token is the one the session route issues
// (double-submit: the cookie is readable by this script, and every unsafe call repeats it in a
// header). Nothing from an answer is written to storage, and a failure says only its status and code.

export type BffResult<T> =
  | { ok: true; status: number; data: T }
  | { ok: false; status: number; code: string };

const CSRF_COOKIE = 'diucs_csrf';
const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

export function csrfFromCookie(): string | null {
  if (typeof document === 'undefined') return null;
  for (const part of document.cookie.split(';')) {
    const at = part.indexOf('=');
    if (at >= 0 && part.slice(0, at).trim() === CSRF_COOKIE) return part.slice(at + 1).trim() || null;
  }
  return null;
}

async function csrfToken(): Promise<string | null> {
  const fromCookie = csrfFromCookie();
  if (fromCookie) return fromCookie;
  // The cookie is not set yet in this tab: the session route issues it and answers the same token.
  const session = await fetch('/api/bff/session', withTraceparent({ cache: 'no-store', credentials: 'same-origin' })).catch(() => null);
  if (!session?.ok) return null;
  const body = (await session.json().catch(() => null)) as { csrfToken?: unknown } | null;
  return typeof body?.csrfToken === 'string' ? body.csrfToken : null;
}

async function codeOf(response: Response): Promise<string> {
  const body = (await response.json().catch(() => null)) as { code?: unknown } | null;
  return typeof body?.code === 'string' ? body.code : 'failed';
}

/** One call to a BFF route. The body is JSON when given. A network failure is status 0. */
export async function bffRequest<T>(path: string, options: { method?: string; body?: unknown } = {}): Promise<BffResult<T>> {
  const method = (options.method ?? (options.body === undefined ? 'GET' : 'POST')).toUpperCase();
  const headers: Record<string, string> = {};
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (UNSAFE.has(method)) {
    const token = await csrfToken();
    if (token) headers['X-CSRF-Token'] = token;
  }
  let response: Response;
  try {
    response = await fetch(path, withTraceparent({
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      cache: 'no-store',
      credentials: 'same-origin',
    }));
  } catch {
    return { ok: false, status: 0, code: 'network' };
  }
  if (!response.ok) return { ok: false, status: response.status, code: await codeOf(response) };
  if (response.status === 204) return { ok: true, status: 204, data: undefined as T };
  return { ok: true, status: response.status, data: (await response.json()) as T };
}
