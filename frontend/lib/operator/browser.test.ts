import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { server } from '@/test/msw/server';
import { OPERATOR_CSRF, signOutOperator } from './browser';

// The operator's sign-out (TEN-083): the session ends at the BFF with the operator's own CSRF token, the
// device is wiped either way, and the person leaves for the console's sign-in only when it did end.

function env() {
  return { fetch: (...a: Parameters<typeof fetch>) => fetch(...a), replace: vi.fn() };
}

describe('signOutOperator', () => {
  it('reads the CSRF token from the session route, ends the session with it and goes to the console sign-in', async () => {
    let sent: string | null = null;
    server.use(
      http.get('/api/bff/platform/session', () => HttpResponse.json({ csrfToken: 'op-csrf' })),
      http.delete('/api/bff/platform/session', ({ request }) => {
        sent = request.headers.get('x-csrf-token');
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const e = env();
    expect(await signOutOperator(e)).toEqual({ signedOut: true });
    expect(sent).toBe('op-csrf');
    expect(e.replace).toHaveBeenCalledWith('/operator/sign-in');
  });

  it('counts a session the back end no longer knows as ended', async () => {
    server.use(http.get('/api/bff/platform/session', () => HttpResponse.json({}, { status: 401 })));
    const e = env();
    expect(await signOutOperator(e)).toEqual({ signedOut: true });
    expect(e.replace).toHaveBeenCalled();
  });

  it('stays, and says it is not signed out, when the session could not be ended', async () => {
    server.use(
      http.get('/api/bff/platform/session', () => HttpResponse.json({ csrfToken: 'x' })),
      http.delete('/api/bff/platform/session', () => HttpResponse.json({}, { status: 500 })),
    );
    const e = env();
    expect(await signOutOperator(e)).toEqual({ signedOut: false });
    expect(e.replace).not.toHaveBeenCalled();
  });

  it('wipes the device even when the session could not be ended', async () => {
    window.localStorage.setItem('k', 'v');
    server.use(http.get('/api/bff/platform/session', () => HttpResponse.json({}, { status: 503 })));
    await signOutOperator(env());
    expect(window.localStorage.length).toBe(0);
  });

  it('uses a cookie and a session route of its own, not the tenant’s', () => {
    expect(OPERATOR_CSRF).toEqual({ cookie: 'diucs_op_csrf', sessionUrl: '/api/bff/platform/session' });
  });
});
