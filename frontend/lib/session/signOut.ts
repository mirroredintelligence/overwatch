// Ending a session in the browser (TEN-050, audit D R8, R9, R10). Sign-out and unpair must leave
// nothing of the person or the tenant on the device, because a shared workstation or a wall screen
// that is moved to another organisation is the next person's:
//
//   1. the session ends on the server (`DELETE /api/bff/session`, which clears the cookies and sends
//      `Clear-Site-Data: "cache", "storage"` for the browsers that act on it);
//   2. the push subscription is removed (a lock-screen notice for the last tenant must not reach the
//      next person);
//   3. every cache is deleted, and `localStorage` and `sessionStorage` are cleared (all of them, not
//      only the app's own keys: Safari ignores Clear-Site-Data);
//   4. the page is left by a HARD navigation (`location.replace`), never a router push, so no script,
//      no client router cache and no page held by the back-forward cache is still there.
//
// Every step is tried even when another fails; the result says which failed, and whether the session
// itself could not be ended (then the page stays, so the person sees it, and the device is wiped
// anyway). Nothing here reads, logs or sends a token, a tenant or a cookie value other than the CSRF
// token the session route issued.

export type WipeStep = 'push' | 'caches' | 'local-storage' | 'session-storage';

type PushSubscriptionLike = { unsubscribe(): Promise<boolean> };
type RegistrationLike = { pushManager: { getSubscription(): Promise<PushSubscriptionLike | null> } };

/** What the browser gives the page, passed in so a test can supply it. */
export type BrowserEnv = {
  fetch: typeof fetch;
  /** `document.cookie`. */
  cookie: string;
  localStorage: Storage | null;
  sessionStorage: Storage | null;
  caches: CacheStorage | undefined;
  serviceWorker: { getRegistration(): Promise<RegistrationLike | undefined> } | undefined;
  location: { replace(url: string): void };
};

export type WipeResult = { failed: WipeStep[] };
export type EndResult = { signedOut: boolean; failed: WipeStep[]; navigated: boolean };

const SESSION_URL = '/api/bff/session';
const CSRF_COOKIE = 'diucs_csrf';
const CSRF_HEADER = 'X-CSRF-Token';
const SIGN_IN = '/sign-in';
const PAIRING = '/screen/pair';

function browserEnv(): BrowserEnv {
  const safe = <T,>(read: () => T): T | null => {
    try {
      return read();
    } catch {
      return null;
    }
  };
  return {
    fetch: (...args) => fetch(...args),
    cookie: document.cookie,
    localStorage: safe(() => window.localStorage),
    sessionStorage: safe(() => window.sessionStorage),
    caches: typeof caches === 'undefined' ? undefined : caches,
    serviceWorker: typeof navigator !== 'undefined' && 'serviceWorker' in navigator ? navigator.serviceWorker : undefined,
    location: window.location,
  };
}

async function removePush(env: BrowserEnv): Promise<boolean> {
  const registration = await env.serviceWorker?.getRegistration();
  const subscription = await registration?.pushManager.getSubscription();
  if (!subscription) return true;
  return subscription.unsubscribe();
}

async function deleteCaches(env: BrowserEnv): Promise<boolean> {
  if (!env.caches) return true;
  const names = await env.caches.keys();
  let ok = true;
  for (const name of names) {
    try {
      if (!(await env.caches.delete(name))) ok = false;
    } catch {
      ok = false;
    }
  }
  return ok;
}

function clearStorage(storage: Storage | null): boolean {
  if (storage === null) return true;
  storage.clear();
  return true;
}

/** The local steps only: push subscription, caches, local and session storage. Each is tried. */
export async function wipeBrowserState(env: BrowserEnv = browserEnv()): Promise<WipeResult> {
  const steps: [WipeStep, () => Promise<boolean> | boolean][] = [
    ['push', () => removePush(env)],
    ['caches', () => deleteCaches(env)],
    ['local-storage', () => clearStorage(env.localStorage)],
    ['session-storage', () => clearStorage(env.sessionStorage)],
  ];
  const failed: WipeStep[] = [];
  for (const [step, run] of steps) {
    try {
      if (!(await run())) failed.push(step);
    } catch {
      failed.push(step);
    }
  }
  return { failed };
}

function csrfFromCookie(cookie: string): string | undefined {
  for (const part of cookie.split(';')) {
    const at = part.indexOf('=');
    if (at > 0 && part.slice(0, at).trim() === CSRF_COOKIE) return part.slice(at + 1).trim() || undefined;
  }
  return undefined;
}

/**
 * Ends the server session. 'ended' for a 204 and for a session that is already gone (a 401);
 * 'failed' for anything else, including no answer.
 */
async function endServerSession(env: BrowserEnv): Promise<'ended' | 'failed'> {
  try {
    let token = csrfFromCookie(env.cookie);
    if (token === undefined) {
      const read = await env.fetch(SESSION_URL, { credentials: 'same-origin', cache: 'no-store' });
      if (read.status === 401) return 'ended';
      if (!read.ok) return 'failed';
      const body = (await read.json()) as { csrfToken?: unknown };
      if (typeof body.csrfToken !== 'string' || body.csrfToken === '') return 'failed';
      token = body.csrfToken;
    }
    const answer = await env.fetch(SESSION_URL, {
      method: 'DELETE',
      credentials: 'same-origin',
      cache: 'no-store',
      headers: { [CSRF_HEADER]: token },
    });
    return answer.status === 204 || answer.status === 401 ? 'ended' : 'failed';
  } catch {
    return 'failed';
  }
}

async function end(env: BrowserEnv, destination: string): Promise<EndResult> {
  const server = await endServerSession(env);
  // The device is wiped whether or not the server answered: a failed sign-out must not leave the
  // next person the last one's stored state.
  const { failed } = await wipeBrowserState(env);
  const signedOut = server === 'ended';
  if (!signedOut) return { signedOut, failed, navigated: false };
  env.location.replace(destination);
  return { signedOut, failed, navigated: true };
}

/** Sign out: end the session, wipe the device, go to the sign-in page. */
export function signOutLocal(env: BrowserEnv = browserEnv()): Promise<EndResult> {
  return end(env, SIGN_IN);
}

/** Unpair a wall screen: end its session, wipe the device, go back to pairing. */
export function unpairLocal(env: BrowserEnv = browserEnv()): Promise<EndResult> {
  return end(env, PAIRING);
}

type PageShowTarget = {
  addEventListener(type: 'pageshow', listener: (event: { persisted: boolean }) => void): void;
  removeEventListener(type: 'pageshow', listener: (event: { persisted: boolean }) => void): void;
};

/**
 * A page the back-forward cache brings back is shown as it was left, after a sign-out too. Such a page
 * is reloaded, so the server decides whether the person may see it. Returns the way to remove it.
 */
export function installBfcacheGuard(target: PageShowTarget, reload: () => void): () => void {
  const onShow = (event: { persisted: boolean }) => {
    if (event.persisted) reload();
  };
  target.addEventListener('pageshow', onShow);
  return () => target.removeEventListener('pageshow', onShow);
}
