import { sealOperatorSession, OPERATOR_COOKIE, type OperatorRole, type OperatorSession } from '@/lib/operator/session';
import { OPERATOR_CSRF_COOKIE, operatorCsrfTokenFor } from '@/lib/operator/csrf';
import { requestWithCookies } from '@/test/cookies';

// Helpers for the operator console's tests: the operator's back-end token (audience `diucs-ops`, NO tenant),
// the sealed operator session, and a request as a signed-in operator would send it. They seal with the real
// `sealOperatorSession`, so a test exercises the real unseal. SESSION_SECRET must be stubbed.

export const OPERATOR_HOST = 'console.example.test';
export const OPERATOR_ACCOUNT = 'ops-0123456789abcdef0123456789abcdef';
export const OPERATOR_NONCE = 'O'.repeat(43);

const SESSION_EXPIRES = new Date(Date.now() + 3_600_000).toISOString();

function part(value: unknown): string {
  return Buffer.from(JSON.stringify(value)).toString('base64url');
}

/** An operator token as the back end issues it: claims `sub role aud exp` and nothing about a tenant. */
export function fakeOperatorToken(role: OperatorRole = 'platform-operator', now: Date = new Date()): string {
  const iat = Math.floor(now.getTime() / 1000);
  return `${part({ alg: 'HS256', typ: 'JWT' })}.${part({ sub: OPERATOR_ACCOUNT, role, aud: 'diucs-ops', iat, exp: iat + 3600 })}.test-signature-not-checked`;
}

export function operatorSessionFor(role: OperatorRole = 'platform-operator', overrides: Partial<OperatorSession> = {}): OperatorSession {
  return {
    role,
    host: OPERATOR_HOST,
    accountRef: OPERATOR_ACCOUNT,
    backendToken: fakeOperatorToken(role),
    expiresAt: SESSION_EXPIRES,
    ...overrides,
  };
}

export function operatorCsrfOf(session: Pick<OperatorSession, 'host' | 'accountRef'> = operatorSessionFor()): string {
  return operatorCsrfTokenFor({ host: session.host, sub: session.accountRef }, OPERATOR_NONCE);
}

export type RequestAsOperatorOptions = {
  method?: string;
  path?: string;
  headers?: Record<string, string>;
  body?: BodyInit;
  cookies?: Record<string, string>;
  session?: Partial<OperatorSession>;
  host?: string;
  /** `true` for the token issued to this session, or the text to send, as cookie and header. */
  csrf?: boolean | string;
};

/** A request from a signed-in operator of `role`, addressed to the operator console's host. */
export async function requestAsOperator(role: OperatorRole = 'platform-operator', options: RequestAsOperatorOptions = {}): Promise<Request> {
  const session = operatorSessionFor(role, options.session);
  const host = options.host ?? OPERATOR_HOST;
  const cookies: Record<string, string> = { [OPERATOR_COOKIE]: await sealOperatorSession(session), ...options.cookies };
  const headers = new Headers(options.headers);
  headers.set('Host', host);
  if (options.csrf !== undefined && options.csrf !== false) {
    const value = options.csrf === true ? operatorCsrfOf(session) : options.csrf;
    cookies[OPERATOR_CSRF_COOKIE] = value;
    headers.set('X-CSRF-Token', value);
  }
  return requestWithCookies(`https://${host}${options.path ?? '/api/bff/platform/session'}`, cookies, {
    method: options.method ?? 'GET',
    headers,
    body: options.body,
  });
}
