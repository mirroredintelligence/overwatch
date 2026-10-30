import { cookies } from 'next/headers';
import { baseCookieOptions, readRequestCookie } from '@/lib/auth/session';

// The phone's device id (DEC-660). The back end reads a device by this id, so the browser holds it
// in an http-only cookie and sends it only from the BFF, never in a URL or a readable value. It is
// random (128 bits, base64url), created once per phone, and kept across sign-outs (the device is
// the same phone; the session is not).

export const DEVICE_COOKIE = 'diucs_device';
const DEVICE_ID = /^[A-Za-z0-9_-]{22}$/;
const DEVICE_BYTES = 16;
/** [ASSUMED] DEC-660: a phone keeps its device id for about a year. */
const DEVICE_MAX_AGE_SECONDS = 365 * 24 * 60 * 60;

/** The device id this request carries, or undefined when the phone has none yet. */
export function deviceIdFromRequest(request: Request): string | undefined {
  const value = readRequestCookie(request, DEVICE_COOKIE);
  return value !== undefined && DEVICE_ID.test(value) ? value : undefined;
}

/** The phone's device id, creating and setting it when the phone has none. Route handlers only. */
export async function ensureDevice(request: Request): Promise<string> {
  const existing = deviceIdFromRequest(request);
  if (existing !== undefined) return existing;
  const bytes = new Uint8Array(DEVICE_BYTES);
  globalThis.crypto.getRandomValues(bytes);
  const id = Buffer.from(bytes).toString('base64url');
  const store = await cookies();
  store.set(DEVICE_COOKIE, id, { ...baseCookieOptions(), httpOnly: true, maxAge: DEVICE_MAX_AGE_SECONDS });
  return id;
}
