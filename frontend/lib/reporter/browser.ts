// The browser's calls to the reporter BFF. Every unsafe call carries the CSRF token from
// /api/bff/reporter/start, which also gives the phone its device cookie. Nothing here keeps a
// phone number, a code or a PIN: a value lives only in the component that asked for it.

export type Reply = { status: number; body: unknown };

const START = '/api/bff/reporter/start';
const PIN_VERIFY = '/api/bff/identity/pin/verify';
let csrf: string | null = null;

async function fetchJson(path: string, init: RequestInit): Promise<Reply> {
  try {
    const response = await fetch(path, { cache: 'no-store', credentials: 'same-origin', ...init });
    let body: unknown = undefined;
    try {
      body = (await response.json()) as unknown;
    } catch {
      body = undefined;
    }
    return { status: response.status, body };
  } catch {
    return { status: 0, body: undefined };
  }
}

async function token(): Promise<string | null> {
  if (csrf !== null) return csrf;
  const reply = await fetchJson(START, { method: 'GET' });
  const value = (reply.body as { csrfToken?: unknown } | undefined)?.csrfToken;
  csrf = typeof value === 'string' ? value : null;
  return csrf;
}

export async function bffRequest(
  path: string,
  options: { method?: 'GET' | 'POST' | 'DELETE'; body?: unknown; headers?: Record<string, string> } = {},
): Promise<Reply> {
  const method = options.method ?? 'GET';
  if (method === 'GET') return fetchJson(path, { method: 'GET' });
  if (method === 'DELETE') {
    const header = await token();
    return fetchJson(path, { method: 'DELETE', headers: { 'X-CSRF-Token': header ?? '' } });
  }
  const send = async () => {
    const header = await token();
    return fetchJson(path, {
      method,
      headers: { ...options.headers, 'Content-Type': 'application/json', 'X-CSRF-Token': header ?? '' },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  };
  const first = await send();
  // A right PIN made a session: the token this page holds was the phone's, and the session's writes need
  // the session's, which the start route now gives (W8E).
  if (path === PIN_VERIFY && first.status === 200 && (first.body as { ok?: unknown } | undefined)?.ok === true) csrf = null;
  // A stale token (another tab rotated it) is refreshed once and the call repeated.
  if (first.status === 403 && (first.body as { code?: string } | undefined)?.code === 'csrf') {
    csrf = null;
    return send();
  }
  return first;
}

/** Forget the cached token (tests and sign-out). */
export function resetBffToken() {
  csrf = null;
}
