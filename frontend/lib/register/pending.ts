import { EncryptJWT, jwtDecrypt } from 'jose';
import { cookies } from 'next/headers';
import { baseCookieOptions, readRequestCookie, sessionSecretKey } from '@/lib/auth/session';

// The sealed record between a registration code request and its check: the device id the back end
// records the code on, and the invitation. Both stay in this cookie, which the browser can neither
// read nor change (it is sealed with the session key). It lives fifteen minutes and only the BFF's
// identity routes can see it (path /api/bff/identity).

export const PENDING_COOKIE = 'diucs_register';
export const PENDING_PATH = '/api/bff/identity';
const LIFETIME_SECONDS = 15 * 60;
const KIND = 'registration-pending';
const ENCRYPTION = { alg: 'dir', enc: 'A256GCM' } as const;
const DEVICE_ID = /^[A-Za-z0-9_-]{22,56}$/;
const INVITE_TOKEN = /^[A-Za-z0-9_-]{16,128}$/;

export type Pending = { deviceId: string; inviteToken: string | undefined };

export async function sealPending(pending: Pending, now: Date = new Date()): Promise<string> {
  const claims: Record<string, unknown> = { kind: KIND, deviceId: pending.deviceId };
  if (pending.inviteToken !== undefined) claims.inviteToken = pending.inviteToken;
  const issued = Math.floor(now.getTime() / 1000);
  return new EncryptJWT(claims)
    .setProtectedHeader(ENCRYPTION)
    .setIssuedAt(issued)
    .setExpirationTime(issued + LIFETIME_SECONDS)
    .encrypt(await sessionSecretKey());
}

/** Null for anything that is not a live pending record of ours. */
export async function unsealPending(value: string, now: Date = new Date()): Promise<Pending | null> {
  if (!value) return null;
  const key = await sessionSecretKey(); // A missing secret is a fault, not "no pending record".
  try {
    const { payload } = await jwtDecrypt(value, key, {
      keyManagementAlgorithms: ['dir'],
      contentEncryptionAlgorithms: ['A256GCM'],
      currentDate: now,
    });
    if (payload.kind !== KIND) return null;
    const { deviceId, inviteToken } = payload;
    if (typeof deviceId !== 'string' || !DEVICE_ID.test(deviceId)) return null;
    if (inviteToken !== undefined && (typeof inviteToken !== 'string' || !INVITE_TOKEN.test(inviteToken))) return null;
    return { deviceId, inviteToken: typeof inviteToken === 'string' ? inviteToken : undefined };
  } catch {
    return null;
  }
}

export async function readPending(request: Request, now: Date = new Date()): Promise<Pending | null> {
  return unsealPending(readRequestCookie(request, PENDING_COOKIE) ?? '', now);
}

export async function issuePending(pending: Pending, now: Date = new Date()): Promise<void> {
  const sealed = await sealPending(pending, now);
  const store = await cookies();
  store.set(PENDING_COOKIE, sealed, { ...baseCookieOptions(), httpOnly: true, path: PENDING_PATH, maxAge: LIFETIME_SECONDS });
}

export async function clearPending(): Promise<void> {
  const store = await cookies();
  store.set(PENDING_COOKIE, '', { ...baseCookieOptions(), httpOnly: true, path: PENDING_PATH, maxAge: 0 });
}
