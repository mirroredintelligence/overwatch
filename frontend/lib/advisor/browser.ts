import { withTraceparent } from '@/lib/telemetry/trace';

// The browser's calls to the advisor BFF (`/api/bff/*`). Staff calls carry the session cookie and,
// for every unsafe method, the CSRF token from GET /api/bff/session (the cookie is not HttpOnly, but
// the page reads its value from that answer). Nothing here sends a tenant, organisation or scope:
// the session says whose data it is (DEC-130, DEC-132). Errors are a status and a code, never a body.

export type BffReply<T> =
  | { ok: true; status: number; body: T }
  | { ok: false; status: number; code: string };

export type BffRequest = {
  method?: 'GET' | 'POST' | 'PUT';
  body?: unknown;
  /** A UUID or other opaque token, generated once per user action (CSRF-checked POSTs). */
  idempotencyKey?: string;
  /** The ETag the page read, sent as If-Match on a PUT. */
  ifMatch?: string;
};

export const CSRF_HEADER = 'X-CSRF-Token';

let csrfCache: Promise<string | null> | null = null;

/** Forgets the CSRF token (tests, and after a session change). */
export function resetCsrfCache(): void {
  csrfCache = null;
}

async function readCsrf(): Promise<string | null> {
  try {
    const response = await fetch(
      '/api/bff/session',
      withTraceparent({ method: 'GET', cache: 'no-store', credentials: 'same-origin' }),
    );
    if (!response.ok) return null;
    const body = (await response.json()) as { csrfToken?: unknown };
    return typeof body.csrfToken === 'string' ? body.csrfToken : null;
  } catch {
    return null;
  }
}

/** The CSRF token for this session. A failed read is not kept, so the next call tries again. */
export function csrfToken(): Promise<string | null> {
  csrfCache ??= readCsrf().then((token) => {
    if (token === null) csrfCache = null;
    return token;
  });
  return csrfCache;
}

async function bodyOf(response: Response): Promise<unknown> {
  try {
    return (await response.json()) as unknown;
  } catch {
    return undefined;
  }
}

function codeOf(body: unknown): string {
  if (typeof body === 'object' && body !== null && 'code' in body) {
    const code = (body as { code: unknown }).code;
    if (typeof code === 'string') return code;
  }
  return 'failed';
}

export async function bffFetch<T>(path: string, request: BffRequest = {}): Promise<BffReply<T>> {
  const method = request.method ?? 'GET';
  const headers: Record<string, string> = {};
  if (request.body !== undefined) headers['Content-Type'] = 'application/json';
  if (request.idempotencyKey !== undefined) headers['Idempotency-Key'] = request.idempotencyKey;
  if (request.ifMatch !== undefined) headers['If-Match'] = request.ifMatch;
  if (method !== 'GET') {
    const token = await csrfToken();
    if (token === null) return { ok: false, status: 0, code: 'csrf' };
    headers[CSRF_HEADER] = token;
  }

  let response: Response;
  try {
    response = await fetch(
      path,
      withTraceparent({
        method,
        headers,
        body: request.body === undefined ? undefined : JSON.stringify(request.body),
        cache: 'no-store',
        credentials: 'same-origin',
      }),
    );
  } catch {
    return { ok: false, status: 0, code: 'unreachable' };
  }

  const body = await bodyOf(response);
  if (response.ok) return { ok: true, status: response.status, body: body as T };
  return { ok: false, status: response.status, code: codeOf(body) };
}

/** A fresh idempotency key for one user action. */
export function newIdempotencyKey(): string {
  return globalThis.crypto.randomUUID();
}
