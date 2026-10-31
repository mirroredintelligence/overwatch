'use client';

import type { CsrfChannel } from '@/lib/bff/browser';
import { wipeBrowserState } from '@/lib/session/signOut';
import { adminSend, useAdminRead, type Read } from '@/lib/tenantAdmin/browser';

// The operator console's calls to its BFF routes (TEN-083). The same helpers as the tenant administration's,
// with the console's own CSRF cookie and session route: an operator's token is never a tenant person's.

export const OPERATOR_CSRF: CsrfChannel = { cookie: 'diucs_op_csrf', sessionUrl: '/api/bff/platform/session' };
export const OPERATOR_SIGN_IN = '/operator/sign-in';

export type { Read };

export function useOperatorRead<T>(path: string | null) {
  return useAdminRead<T>(path, OPERATOR_CSRF);
}

export function operatorSend<T>(method: 'POST' | 'PUT' | 'DELETE', path: string, body: unknown, key: string) {
  return adminSend<T>(method, path, body, key, OPERATOR_CSRF);
}

export type OperatorSignOutEnv = {
  fetch: typeof fetch;
  replace: (url: string) => void;
};

function browserEnv(): OperatorSignOutEnv {
  return { fetch: (...args) => fetch(...args), replace: (url) => window.location.replace(url) };
}

function csrfFromCookie(): string | undefined {
  for (const part of document.cookie.split(';')) {
    const at = part.indexOf('=');
    if (at > 0 && part.slice(0, at).trim() === OPERATOR_CSRF.cookie) return part.slice(at + 1).trim() || undefined;
  }
  return undefined;
}

/**
 * Signs the operator out: ends the session at the BFF (`DELETE /api/bff/platform/session`, which drops the
 * cookies and sends Clear-Site-Data), wipes what the browser holds whether or not that worked, and leaves
 * by a hard navigation to the console's sign-in. A session that could not be ended is said so and stays.
 */
export async function signOutOperator(env: OperatorSignOutEnv = browserEnv()): Promise<{ signedOut: boolean }> {
  let ended = false;
  try {
    let token = csrfFromCookie();
    if (token === undefined) {
      const read = await env.fetch('/api/bff/platform/session', { credentials: 'same-origin', cache: 'no-store' });
      if (read.status === 401) ended = true;
      else if (read.ok) token = ((await read.json()) as { csrfToken?: string }).csrfToken;
    }
    if (!ended && token !== undefined) {
      const answer = await env.fetch('/api/bff/platform/session', { method: 'DELETE', credentials: 'same-origin', cache: 'no-store', headers: { 'X-CSRF-Token': token } });
      ended = answer.status === 204 || answer.status === 401;
    }
  } catch {
    ended = false;
  }
  await wipeBrowserState();
  if (ended) env.replace(OPERATOR_SIGN_IN);
  return { signedOut: ended };
}
