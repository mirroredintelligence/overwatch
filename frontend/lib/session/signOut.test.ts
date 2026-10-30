import { describe, expect, it, vi } from 'vitest';
import { installBfcacheGuard, signOutLocal, unpairLocal, wipeBrowserState, type BrowserEnv } from './signOut';

// Sign-out and unpair leave nothing of the person or the tenant on the device (TEN-050, audit D R8,
// R9, R10): the server session ends, the push subscription is removed, every cache and every stored
// value is deleted, and the page is left by a hard navigation, so no script, no router cache and no
// back-forward cache still holds a page of the session. Each step is tried even when another fails,
// and the person is told when the session itself could not be ended.

function storageWith(entries: Record<string, string>): Storage {
  const data = new Map(Object.entries(entries));
  return {
    get length() { return data.size; },
    clear: () => data.clear(),
    getItem: (k) => data.get(k) ?? null,
    key: (i) => [...data.keys()][i] ?? null,
    removeItem: (k) => void data.delete(k),
    setItem: (k, v) => void data.set(k, v),
  };
}

type Calls = { fetches: { url: string; init?: RequestInit }[]; replaced: string[]; unsubscribed: number; deletedCaches: string[] };

function makeEnv(overrides: Partial<BrowserEnv> = {}, answers: { get?: Response | Error; del?: Response | Error } = {}) {
  const calls: Calls = { fetches: [], replaced: [], unsubscribed: 0, deletedCaches: [] };
  const localStorage = storageWith({ 'diucs:v1:tenant-a.example.test:tour.seen': 'true', unrelated: 'x' });
  const sessionStorage = storageWith({ 'telemetry.session': 'abc' });
  const env: BrowserEnv = {
    fetch: vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      calls.fetches.push({ url: String(url), init });
      const answer = init?.method === 'DELETE' ? (answers.del ?? new Response(null, { status: 204 })) : (answers.get ?? Response.json({ role: 'advisor', services: [], csrfToken: 'fetched-token' }));
      if (answer instanceof Error) throw answer;
      return answer.clone();
    }) as unknown as typeof fetch,
    cookie: 'other=1; diucs_csrf=cookie-token; more=2',
    localStorage,
    sessionStorage,
    caches: {
      keys: async () => ['static-v1', 'pages-v1'],
      delete: async (name: string) => { calls.deletedCaches.push(name); return true; },
    } as unknown as CacheStorage,
    serviceWorker: {
      getRegistration: async () => ({
        pushManager: { getSubscription: async () => ({ unsubscribe: async () => { calls.unsubscribed += 1; return true; } }) },
      }),
    } as unknown as BrowserEnv['serviceWorker'],
    location: { replace: (url: string) => void calls.replaced.push(url) },
    ...overrides,
  };
  return { env, calls, localStorage, sessionStorage };
}

describe('signOutLocal', () => {
  it('ends the session on the server with the CSRF token from the cookie, then wipes, then leaves by a hard navigation', async () => {
    const { env, calls, localStorage, sessionStorage } = makeEnv();
    const result = await signOutLocal(env);
    expect(result).toEqual({ signedOut: true, failed: [], navigated: true });
    expect(calls.fetches).toHaveLength(1);
    expect(calls.fetches[0]?.url).toBe('/api/bff/session');
    expect(calls.fetches[0]?.init).toMatchObject({ method: 'DELETE', credentials: 'same-origin', cache: 'no-store' });
    expect(new Headers(calls.fetches[0]?.init?.headers).get('X-CSRF-Token')).toBe('cookie-token');
    expect(calls.unsubscribed).toBe(1);
    expect(calls.deletedCaches).toEqual(['static-v1', 'pages-v1']);
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(calls.replaced).toEqual(['/sign-in']);
  });

  it('wipes every key of the origin, not only the app’s own', async () => {
    const { env, localStorage } = makeEnv();
    expect(localStorage.getItem('unrelated')).toBe('x');
    await signOutLocal(env);
    expect(localStorage.getItem('unrelated')).toBeNull();
  });

  it('fetches a CSRF token from the session when the cookie has none, and sends no body and no tenant', async () => {
    const { env, calls } = makeEnv({ cookie: 'other=1' });
    await signOutLocal(env);
    expect(calls.fetches.map((f) => f.init?.method ?? 'GET')).toEqual(['GET', 'DELETE']);
    expect(new Headers(calls.fetches[1]?.init?.headers).get('X-CSRF-Token')).toBe('fetched-token');
    for (const f of calls.fetches) {
      expect(f.init?.body).toBeUndefined();
      expect(f.url).not.toMatch(/tenant|scope|network/i);
      expect([...new Headers(f.init?.headers).keys()].join(' ')).not.toMatch(/tenant|scope|network|authorization/i);
    }
  });

  it('counts a session that is already gone (401 on the token or on the delete) as signed out', async () => {
    for (const answers of [{ get: new Response('{}', { status: 401 }) }, { del: new Response('{}', { status: 401 }) }]) {
      const { env, calls } = makeEnv(answers.get ? { cookie: '' } : {}, answers);
      const result = await signOutLocal(env);
      expect(result.signedOut).toBe(true);
      expect(calls.replaced).toEqual(['/sign-in']);
    }
  });

  it('wipes the device but does not leave the page, and says so, when the session could not be ended', async () => {
    for (const del of [new Response('{}', { status: 500 }), new Response('{}', { status: 403 }), new Error('offline')]) {
      const { env, calls, localStorage } = makeEnv({}, { del });
      const result = await signOutLocal(env);
      expect(result).toEqual({ signedOut: false, failed: [], navigated: false });
      expect(calls.replaced).toEqual([]);
      expect(localStorage.length).toBe(0);
      expect(calls.unsubscribed).toBe(1);
    }
  });

  it('does not treat a failed token fetch as signed out', async () => {
    const { env, calls } = makeEnv({ cookie: '' }, { get: new Error('offline') });
    const result = await signOutLocal(env);
    expect(result.signedOut).toBe(false);
    expect(calls.replaced).toEqual([]);
  });

  it('tries every step even when one throws, and names the ones that failed', async () => {
    const { env, calls } = makeEnv({
      caches: { keys: async () => { throw new Error('no caches'); }, delete: async () => true } as unknown as CacheStorage,
      serviceWorker: { getRegistration: async () => { throw new Error('no worker'); } } as unknown as BrowserEnv['serviceWorker'],
      localStorage: { clear: () => { throw new Error('blocked'); } } as unknown as Storage,
    });
    const result = await signOutLocal(env);
    expect(result.failed.sort()).toEqual(['caches', 'local-storage', 'push']);
    expect(result.signedOut).toBe(true);
    expect(calls.replaced).toEqual(['/sign-in']);
  });

  it('leaves by replace, never by a router push, and to a fixed place', async () => {
    const { env, calls } = makeEnv();
    const assign = vi.fn();
    (env.location as unknown as Record<string, unknown>).assign = assign;
    await signOutLocal(env);
    expect(assign).not.toHaveBeenCalled();
    expect(calls.replaced).toEqual(['/sign-in']);
  });

  it('writes nothing to the console: no token, cookie or tenant', async () => {
    const spies = (['log', 'info', 'warn', 'error', 'debug'] as const).map((m) => vi.spyOn(console, m).mockImplementation(() => undefined));
    const { env } = makeEnv({ localStorage: { clear: () => { throw new Error('cookie-token'); } } as unknown as Storage });
    await signOutLocal(env);
    for (const spy of spies) expect(spy).not.toHaveBeenCalled();
    vi.restoreAllMocks();
  });
});

describe('unpairLocal', () => {
  it('does the same and goes back to pairing', async () => {
    const { env, calls, localStorage } = makeEnv();
    const result = await unpairLocal(env);
    expect(result).toEqual({ signedOut: true, failed: [], navigated: true });
    expect(calls.fetches[0]?.init?.method).toBe('DELETE');
    expect(localStorage.length).toBe(0);
    expect(calls.replaced).toEqual(['/screen/pair']);
  });

  it('still wipes and still goes to pairing when the screen’s session is already refused (a revoked screen)', async () => {
    const { env, calls, localStorage } = makeEnv({}, { del: new Response('{}', { status: 401 }) });
    const result = await unpairLocal(env);
    expect(result.signedOut).toBe(true);
    expect(localStorage.length).toBe(0);
    expect(calls.replaced).toEqual(['/screen/pair']);
  });
});

describe('wipeBrowserState', () => {
  it('does the local steps only: no request, no navigation', async () => {
    const { env, calls, localStorage, sessionStorage } = makeEnv();
    expect(await wipeBrowserState(env)).toEqual({ failed: [] });
    expect(calls.fetches).toEqual([]);
    expect(calls.replaced).toEqual([]);
    expect(localStorage.length + sessionStorage.length).toBe(0);
    expect(calls.unsubscribed).toBe(1);
    expect(calls.deletedCaches).toHaveLength(2);
  });

  it('is fine where there is no service worker, no caches and no storage (a server, an old browser)', async () => {
    const { env } = makeEnv({ caches: undefined, serviceWorker: undefined, localStorage: null, sessionStorage: null });
    expect(await wipeBrowserState(env)).toEqual({ failed: [] });
  });

  it('is fine where there is no push registration, and says failed when a subscription would not unsubscribe', async () => {
    const none = makeEnv({ serviceWorker: { getRegistration: async () => undefined } as unknown as BrowserEnv['serviceWorker'] });
    expect(await wipeBrowserState(none.env)).toEqual({ failed: [] });
    const stuck = makeEnv({
      serviceWorker: { getRegistration: async () => ({ pushManager: { getSubscription: async () => ({ unsubscribe: async () => false }) } }) } as unknown as BrowserEnv['serviceWorker'],
    });
    expect(await wipeBrowserState(stuck.env)).toEqual({ failed: ['push'] });
  });

  it('keeps deleting caches when one will not delete, and names the step', async () => {
    const deleted: string[] = [];
    const { env } = makeEnv({
      caches: { keys: async () => ['a', 'b', 'c'], delete: async (n: string) => { deleted.push(n); if (n === 'b') throw new Error('x'); return true; } } as unknown as CacheStorage,
    });
    expect(await wipeBrowserState(env)).toEqual({ failed: ['caches'] });
    expect(deleted).toEqual(['a', 'b', 'c']);
  });
});

describe('installBfcacheGuard', () => {
  function target() {
    const listeners = new Map<string, (event: { persisted: boolean }) => void>();
    return {
      listeners,
      addEventListener: vi.fn((type: string, fn: (event: { persisted: boolean }) => void) => void listeners.set(type, fn)),
      removeEventListener: vi.fn((type: string) => void listeners.delete(type)),
    };
  }

  it('reloads a page that the back-forward cache brings back, so a signed-out person never sees the page they left', () => {
    const t = target();
    const reload = vi.fn();
    installBfcacheGuard(t, reload);
    t.listeners.get('pageshow')?.({ persisted: true });
    expect(reload).toHaveBeenCalledOnce();
  });

  it('does nothing for an ordinary page show', () => {
    const t = target();
    const reload = vi.fn();
    installBfcacheGuard(t, reload);
    t.listeners.get('pageshow')?.({ persisted: false });
    expect(reload).not.toHaveBeenCalled();
  });

  it('removes its listener when asked', () => {
    const t = target();
    const remove = installBfcacheGuard(t, vi.fn());
    remove();
    expect(t.removeEventListener).toHaveBeenCalledWith('pageshow', expect.any(Function));
    expect(t.listeners.size).toBe(0);
  });
});
