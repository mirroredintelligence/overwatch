import { hkdfSync } from 'node:crypto';
import { cookies } from 'next/headers';
import { EncryptJWT, jwtDecrypt } from 'jose';
import { baseCookieOptions, readRequestCookie, sessionSecretKey } from '@/lib/auth/session';

// Two sealed cookies a wall display holds, each with a key of its own (derived from the session
// secret), so neither can pass as the other or as a session. Both are HttpOnly, Secure, SameSite
// Strict and limited to the screen routes: the page's script cannot read them and no other route
// receives them.
//
//   diucs_pairing  while the code is on screen: the pairing id and the secret that proves this
//                  display is the one that asked (it is in no body, address or log)
//   diucs_device   once a lead has connected it: the opaque device token. The back end gives it once
//                  and it is traded for a one-hour wall token whenever the session ends (TEN-043)

export const PAIRING_COOKIE = 'diucs_pairing';
export const DEVICE_COOKIE = 'diucs_device';

const COOKIE_PATH = '/api/bff/screens';
const PAIRING_SECONDS = 600; // the back end's own ten minutes (U10)
// [ASSUMED] The device token does not expire by itself: it lives until the lead revokes the screen
// (U37), which the screen learns at its next trade. A browser keeps a cookie for 400 days at most.
const DEVICE_SECONDS = 400 * 86_400;
const ENCRYPTION = { alg: 'dir', enc: 'A256GCM' } as const;
const PAIRING_ID = /^[A-Za-z0-9_-]{1,64}$/;
const VISIBLE = /^[\x21-\x7e]+$/;
const SECRET_MAX = 256;
const DEVICE_TOKEN_MAX = 1024;

const PURPOSE = { pairing: 'pairing-cookie-v1', device: 'device-cookie-v1' } as const;

function keyFor(purpose: keyof typeof PURPOSE): Uint8Array {
  return new Uint8Array(hkdfSync('sha256', sessionSecretKey(), 'diucs-wall-screen', PURPOSE[purpose], 32));
}

function options(maxAge: number) {
  return { ...baseCookieOptions(), httpOnly: true, path: COOKIE_PATH, maxAge };
}

async function seal(purpose: keyof typeof PURPOSE, claims: Record<string, string>, seconds: number): Promise<string> {
  const now = Math.floor(Date.now() / 1000);
  return new EncryptJWT(claims).setProtectedHeader(ENCRYPTION).setIssuedAt(now).setExpirationTime(now + seconds).encrypt(keyFor(purpose));
}

async function open(purpose: keyof typeof PURPOSE, request: Request, name: string): Promise<Record<string, unknown> | null> {
  const key = keyFor(purpose); // A missing secret is a fault, not "no cookie".
  const value = readRequestCookie(request, name);
  if (!value) return null;
  try {
    const { payload } = await jwtDecrypt(value, key, {
      keyManagementAlgorithms: ['dir'],
      contentEncryptionAlgorithms: ['A256GCM'],
    });
    return payload;
  } catch {
    return null;
  }
}

export type Pairing = { pairingId: string; screenSecret: string };

export async function rememberPairing(pairing: Pairing): Promise<void> {
  if (!PAIRING_ID.test(pairing.pairingId) || !VISIBLE.test(pairing.screenSecret) || pairing.screenSecret.length > SECRET_MAX) {
    throw new Error('The pairing cannot be kept');
  }
  const sealed = await seal('pairing', { pairingId: pairing.pairingId, screenSecret: pairing.screenSecret }, PAIRING_SECONDS);
  (await cookies()).set(PAIRING_COOKIE, sealed, options(PAIRING_SECONDS));
}

export async function pairingFrom(request: Request): Promise<Pairing | null> {
  const payload = await open('pairing', request, PAIRING_COOKIE);
  if (payload === null) return null;
  const { pairingId, screenSecret } = payload;
  if (typeof pairingId !== 'string' || !PAIRING_ID.test(pairingId)) return null;
  if (typeof screenSecret !== 'string' || !VISIBLE.test(screenSecret) || screenSecret.length > SECRET_MAX) return null;
  return { pairingId, screenSecret };
}

export async function forgetPairing(): Promise<void> {
  (await cookies()).set(PAIRING_COOKIE, '', options(0));
}

export async function rememberDevice(deviceToken: string): Promise<void> {
  if (!VISIBLE.test(deviceToken) || deviceToken.length > DEVICE_TOKEN_MAX) throw new Error('The device token cannot be kept');
  const sealed = await seal('device', { deviceToken }, DEVICE_SECONDS);
  (await cookies()).set(DEVICE_COOKIE, sealed, options(DEVICE_SECONDS));
}

export async function deviceFrom(request: Request): Promise<string | null> {
  const payload = await open('device', request, DEVICE_COOKIE);
  const token = payload?.deviceToken;
  return typeof token === 'string' && VISIBLE.test(token) && token.length <= DEVICE_TOKEN_MAX ? token : null;
}

export async function forgetDevice(): Promise<void> {
  (await cookies()).set(DEVICE_COOKIE, '', options(0));
}
