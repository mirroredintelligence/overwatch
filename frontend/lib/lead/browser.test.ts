import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { csrfTokenForWrite, leadPost } from './browser';

// A write from the lead's browser carries the CSRF token (DEC-1329). When the cookie is not set yet, the
// token comes from the session route, which issues the cookie; without it the BFF refuses the write (403).

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
  document.cookie = 'overwatch_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT';
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = 'overwatch_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT';
});

describe('the CSRF token for a lead write', () => {
  it('takes the token from the cookie when it is set, without asking the session route', async () => {
    document.cookie = 'overwatch_csrf=token-from-cookie';
    expect(await csrfTokenForWrite()).toBe('token-from-cookie');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('asks the session route for the token when the cookie is not set yet', async () => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ csrfToken: 'token-from-session' }), { status: 200 }));
    expect(await csrfTokenForWrite()).toBe('token-from-session');
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/bff/session');
  });

  it('sends the token with the write, so a first write from a fresh sign-in is not refused', async () => {
    fetchMock
      .mockResolvedValueOnce(new Response(JSON.stringify({ csrfToken: 'token-from-session' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ prefix: 'DT4', status: 'queued' }), { status: 202 }));
    const result = await leadPost('/api/bff/postcode-districts/download?text=DT4', {});
    expect(result.ok).toBe(true);
    const init = fetchMock.mock.calls[1]?.[1] as RequestInit;
    expect((init.headers as Record<string, string>)['X-CSRF-Token']).toBe('token-from-session');
  });
});
