import { hkdfSync } from 'node:crypto';
import { cookies } from 'next/headers';
import { EncryptJWT, jwtDecrypt } from 'jose';
import { isSamePathOnly } from './access';
import {
  authorizeUrl,
  exchangeCode,
  loadEntraConfig,
  newTransaction,
  SignInRefused,
  verifyIdToken,
  type Transaction,
} from './oidc';
import {
  baseCookieOptions,
  createSession,
  readRequestCookie,
  sessionSecretKey,
} from './session';
import { backendTokenExpiresAt, mapRoles, mintBackendToken, safeNext } from './staff';

// The two halves of staff sign-in: start (send the browser to Entra) and complete (the browser
// comes back with a code). The tenant is never read from the request: it comes from the directory
// of the verified ID token and from nothing else. Nothing here logs a token, code or claim.

export const TRANSACTION_COOKIE = 'diucs_oidc';
const TRANSACTION_PATH = '/api/bff/auth/entra';
const TRANSACTION_SECONDS = 600;
const ENCRYPTION = { alg: 'dir', enc: 'A256GCM' } as const;

const FAILED = '/sign-in?error=failed';
const NO_ACCESS = '/sign-in?error=no-access';
const FORBIDDEN = '/forbidden';

const BASE64URL_43 = /^[A-Za-z0-9_-]{43}$/;
const CODE_MAX_LENGTH = 2048;

function see(location: string): Response {
  return new Response(null, { status: 303, headers: { Location: location, 'Cache-Control': 'no-store' } });
}

// The transaction cookie is sealed with a key derived from the session secret for this one
// purpose, so a sealed session can never be passed off as a transaction or the other way round.
function transactionKey(): Uint8Array {
  const derived = hkdfSync('sha256', sessionSecretKey(), 'diucs-staff-sign-in', 'transaction-cookie-v1', 32);
  return new Uint8Array(derived);
}

async function sealTransaction(transaction: Transaction, now: Date): Promise<string> {
  const seconds = Math.floor(now.getTime() / 1000);
  return new EncryptJWT({ ...transaction })
    .setProtectedHeader(ENCRYPTION)
    .setIssuedAt(seconds)
    .setExpirationTime(seconds + TRANSACTION_SECONDS)
    .encrypt(transactionKey());
}

async function unsealTransaction(value: string, now: Date): Promise<Transaction | null> {
  const key = transactionKey(); // A missing secret is a fault, not "no transaction".
  if (!value) return null;
  try {
    const { payload } = await jwtDecrypt(value, key, {
      keyManagementAlgorithms: ['dir'],
      contentEncryptionAlgorithms: ['A256GCM'],
      currentDate: now,
    });
    const { state, nonce, verifier, next } = payload;
    if (typeof state !== 'string' || !BASE64URL_43.test(state)) return null;
    if (typeof nonce !== 'string' || !BASE64URL_43.test(nonce)) return null;
    if (typeof verifier !== 'string' || !BASE64URL_43.test(verifier)) return null;
    if (typeof next !== 'string' || (next !== '' && !isSamePathOnly(next))) return null;
    return { state, nonce, verifier, next };
  } catch {
    return null;
  }
}

function transactionCookie(maxAge: number) {
  // Lax, not Strict: the browser comes back from Entra on a cross-site navigation, and a Strict
  // cookie is not sent on one. The session cookie, set after the checks, is Strict.
  return { ...baseCookieOptions(), httpOnly: true, sameSite: 'lax' as const, path: TRANSACTION_PATH, maxAge };
}

// A fixed word per refusal, so an operator can tell a forged callback from a broken set-up without
// a token, code or claim ever reaching the log.
function note(reason: string): void {
  console.warn(`staff sign-in refused: ${reason}`);
}

async function nextFrom(request: Request): Promise<string> {
  try {
    const next = (await request.formData()).get('next');
    return typeof next === 'string' && isSamePathOnly(next) ? next : '';
  } catch {
    return '';
  }
}

/** POST: the browser is sent to Entra. Reads `next` from the form and nothing else from the request. */
export async function startSignIn(request: Request): Promise<Response> {
  try {
    const config = loadEntraConfig();
    const transaction = newTransaction(await nextFrom(request));
    const sealed = await sealTransaction(transaction, new Date());
    const store = await cookies();
    store.set(TRANSACTION_COOKIE, sealed, transactionCookie(TRANSACTION_SECONDS));
    return see(authorizeUrl(config, transaction).toString());
  } catch {
    note('could not start');
    return see(FAILED);
  }
}

// A page that moves the browser on, not a redirect. The browser came here from Entra, so a redirect
// from this response would still count as cross-site and the Strict session cookie just set would
// not be sent with it. A navigation the page starts itself is same-site.
function moveOn(destination: string): Response {
  const href = destination.replaceAll('&', '&amp;');
  const html =
    '<!doctype html><html lang="en-GB"><head><meta charset="utf-8">' +
    `<meta http-equiv="refresh" content="0;url=${href}">` +
    '<meta name="robots" content="noindex"><title>Signing you in</title></head>' +
    `<body><p>Signing you in. <a href="${href}">Continue</a></p></body></html>`;
  return new Response(html, {
    status: 200,
    headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer' },
  });
}

/** GET: the browser is back from Entra. Checks everything, then creates our own session. */
export async function completeSignIn(request: Request): Promise<Response> {
  try {
    const config = loadEntraConfig();
    const store = await cookies();
    const now = new Date();
    // The transaction is single-use: gone from the browser whatever happens next.
    store.set(TRANSACTION_COOKIE, '', transactionCookie(0));

    const transaction = await unsealTransaction(readRequestCookie(request, TRANSACTION_COOKIE) ?? '', now);
    if (!transaction) throw new SignInRefused('transaction');

    const query = new URL(request.url).searchParams;
    if (query.has('error')) throw new SignInRefused('provider-error');
    const state = query.get('state');
    const code = query.get('code');
    if (state !== transaction.state) throw new SignInRefused('state');
    if (!code || code.length > CODE_MAX_LENGTH) throw new SignInRefused('state');

    const idToken = await exchangeCode(config, code, transaction);
    const identity = await verifyIdToken(config, idToken, transaction.nonce, now);

    const role = mapRoles(identity.roles, { allowSupport: identity.binding.platform });
    if (role === null) return see(NO_ACCESS);

    const backendToken = await mintBackendToken(
      { oid: identity.oid, role, tenantId: identity.binding.tenantId },
      now,
    );
    await createSession({
      role,
      services: [],
      sub: identity.oid,
      backendToken,
      expiresAt: backendTokenExpiresAt(now).toISOString(),
    });
    return moveOn(safeNext(transaction.next, role));
  } catch (error) {
    if (error instanceof SignInRefused) {
      note(error.reason);
      return see(error.reason === 'unbound-directory' ? FORBIDDEN : FAILED);
    }
    note('fault');
    return see(FAILED);
  }
}
