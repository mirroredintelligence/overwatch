// The shift lead pages' calls to the BFF from the browser (W17, W18, W42, W43, W47). Every write sends
// the CSRF token from the cookie the BFF set, and one Idempotency-Key per submit, so a repeat of the
// same submit is a replay, not a second change (DEC-653).

export const CSRF_COOKIE = 'diucs_csrf';

/** The CSRF token the BFF set for this browser, or undefined when there is none. */
export function csrfToken(): string | undefined {
  try {
    for (const part of document.cookie.split(';')) {
      const at = part.indexOf('=');
      if (at >= 0 && part.slice(0, at).trim() === CSRF_COOKIE) {
        const value = part.slice(at + 1).trim();
        return value.length > 0 ? value : undefined;
      }
    }
  } catch {
    return undefined;
  }
  return undefined;
}

/** A new key for one submit: a random UUID where the browser has one, else random hex. */
export function newIdempotencyKey(): string {
  const random = globalThis.crypto;
  if (random && typeof random.randomUUID === 'function') return random.randomUUID();
  const bytes = new Uint8Array(16);
  random.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

export type LeadResult =
  | { ok: true; status: number; body: unknown }
  | { ok: false; status: number; code: string | undefined };

/** Sends one write to the BFF. The outcome says what the page should show. */
export async function leadPost(path: string, body?: unknown, idempotencyKey?: string): Promise<LeadResult> {
  const headers: Record<string, string> = {
    'X-CSRF-Token': csrfToken() ?? '',
    'Idempotency-Key': idempotencyKey ?? newIdempotencyKey(),
  };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  let response: Response;
  try {
    response = await fetch(path, {
      method: 'POST',
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: 'no-store',
      credentials: 'same-origin',
    });
  } catch {
    return { ok: false, status: 0, code: undefined };
  }
  let parsed: unknown;
  try {
    parsed = await response.json();
  } catch {
    parsed = undefined;
  }
  if (response.ok) return { ok: true, status: response.status, body: parsed };
  const code = typeof (parsed as { code?: unknown } | undefined)?.code === 'string'
    ? (parsed as { code: string }).code
    : undefined;
  return { ok: false, status: response.status, code };
}

/** Reads one lead GET. Throws on any failure, so the caller decides what the page shows. */
export async function leadGet(path: string): Promise<unknown> {
  const response = await fetch(path, { method: 'GET', cache: 'no-store', credentials: 'same-origin' });
  if (!response.ok) throw new Error(`GET ${path} answered ${response.status}`);
  return response.json();
}
