// The browser's calls to the BFF (`/api/bff/*`). Each returns what the page needs, or a code and a
// status when it failed. The CSRF token comes from the session read, is kept in memory only (never
// in storage) and is sent on every unsafe request. Each POST carries an idempotency key, so a
// retried submit is one write on the back end.

export type BffResult<T> = { ok: true; data: T } | { ok: false; status: number; code: string };

let csrf: string | null = null;

async function csrfToken(): Promise<string | null> {
  if (csrf !== null) return csrf;
  try {
    const response = await fetch('/api/bff/session', {
      method: 'GET',
      cache: 'no-store',
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) return null;
    const body = (await response.json()) as { csrfToken?: unknown };
    csrf = typeof body.csrfToken === 'string' ? body.csrfToken : null;
    return csrf;
  } catch {
    return null;
  }
}

async function codeOf(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { code?: unknown };
    return typeof body.code === 'string' ? body.code : 'exception';
  } catch {
    return 'exception';
  }
}

/** A new idempotency key: 36 printable characters, one per submit. */
export function newIdempotencyKey(): string {
  return globalThis.crypto.randomUUID();
}

export async function bffGet<T>(path: string, parse: (value: unknown) => T): Promise<BffResult<T>> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: 'GET',
      cache: 'no-store',
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    });
  } catch {
    return { ok: false, status: 0, code: 'network' };
  }
  if (!response.ok) return { ok: false, status: response.status, code: await codeOf(response) };
  try {
    return { ok: true, data: parse((await response.json()) as unknown) };
  } catch {
    return { ok: false, status: response.status, code: 'invalid' };
  }
}

export async function bffPost(path: string, body?: unknown, key: string = newIdempotencyKey()): Promise<BffResult<unknown>> {
  const token = await csrfToken();
  if (token === null) return { ok: false, status: 0, code: 'no-session' };
  let response: Response;
  try {
    response = await fetch(path, {
      method: 'POST',
      cache: 'no-store',
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        'X-CSRF-Token': token,
        'Idempotency-Key': key,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    return { ok: false, status: 0, code: 'network' };
  }
  if (!response.ok) {
    if (response.status === 403) csrf = null;
    return { ok: false, status: response.status, code: await codeOf(response) };
  }
  const text = await response.text();
  return { ok: true, data: text === '' ? undefined : (JSON.parse(text) as unknown) };
}
