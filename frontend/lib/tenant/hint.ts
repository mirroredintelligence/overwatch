import { cookies } from 'next/headers';
import { baseCookieOptions } from '@/lib/auth/session';

// Server-only. Which organisation a page with no login belongs to (DEC-1354). The deployment has one host name,
// so for a reporter's phone, a wall display or a link the organisation comes from what the person holds: a link
// carries the organisation's letters in front of its 23-letter token, and the BFF keeps them in a cookie so the
// later calls from the same phone or display (device code, PIN, push key, screen pairing) name it too.
//
// The letters are only where the back end looks: it takes them from this app alone (with the edge secret), and
// whatever it reads there it reads by a secret the person must hold. They are the tenant id written with letters
// only (a to z stay, 0 to 9 become A to J, the hyphen K), the same one-to-one mapping as the back end's
// `tenant_letters`, so a link never holds a digit or a hyphen.

export const TENANT_COOKIE = 'overwatch_tenant';
export const TENANT_HEADER = 'X-Overwatch-Tenant';
const LETTERS = /^[A-Za-z]{2,31}$/;
const TOKEN_LENGTH = 23;
const ONE_YEAR_SECONDS = 365 * 24 * 60 * 60;

export function isTenantLetters(value: unknown): value is string {
  return typeof value === 'string' && LETTERS.test(value);
}

/** The letters of a tenant id (lower case, digits and hyphen), or null when it is not one. */
export function tenantLetters(tenantId: string): string | null {
  if (!/^[a-z0-9][a-z0-9-]{1,30}$/.test(tenantId)) return null;
  let out = '';
  for (const char of tenantId) {
    if (char === '-') out += 'K';
    else if (char >= '0' && char <= '9') out += String.fromCharCode('A'.charCodeAt(0) + Number(char));
    else out += char;
  }
  return out;
}

/** The organisation's letters in front of a link token, or null for a token with none (or text that is not a link). */
export function lettersOfToken(text: unknown): string | null {
  if (typeof text !== 'string' || text.length <= TOKEN_LENGTH || text.length > TOKEN_LENGTH + 31) return null;
  const head = text.slice(0, -TOKEN_LENGTH);
  const tail = text.slice(-TOKEN_LENGTH);
  return isTenantLetters(head) && /^[A-Za-z]+$/.test(tail) ? head : null;
}

/** The letters a call names by a token in its path or in the body's `invitation` / `invite` field. */
export function lettersOfCall(call: { path: string; body?: unknown }): string | null {
  for (const segment of call.path.split(/[/?]/)) {
    const found = lettersOfToken(segment);
    if (found !== null) return found;
  }
  if (typeof call.body === 'object' && call.body !== null) {
    const fields = call.body as Record<string, unknown>;
    return lettersOfToken(fields.invitation) ?? lettersOfToken(fields.invite);
  }
  return null;
}

/** The letters this phone or display remembered, or null (no cookie, or not inside a request). */
export async function rememberedLetters(): Promise<string | null> {
  try {
    const value = (await cookies()).get(TENANT_COOKIE)?.value;
    return isTenantLetters(value) ? value : null;
  } catch {
    return null;
  }
}

/** Remember the letters on this phone or display. Best effort: where cookies cannot be set the call still goes. */
export async function rememberLetters(letters: string): Promise<void> {
  if (!isTenantLetters(letters)) return;
  try {
    (await cookies()).set(TENANT_COOKIE, letters, { ...baseCookieOptions(), httpOnly: true, path: '/', maxAge: ONE_YEAR_SECONDS });
  } catch {
    // Outside a route handler, or in a test: nothing to remember it in.
  }
}
