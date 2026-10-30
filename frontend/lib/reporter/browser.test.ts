import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { server } from '@/test/msw/server';
import { bffRequest, resetBffToken } from './browser';

// The reporter pages' calls to the BFF (W33 to W55, W8E). A write carries the CSRF token from
// /api/bff/reporter/start. That token is the phone's before sign-in and the session's after it, so the
// page must ask again once a PIN sign-in has succeeded, and once when a write is refused for a stale
// token. Nothing here keeps a number, a code or a PIN.

const seen: { path: string; csrf: string | null }[] = [];
let startCalls = 0;
let issued = 'T1';

beforeEach(() => {
  resetBffToken();
  seen.length = 0;
  startCalls = 0;
  issued = 'T1';
  server.use(
    http.get('/api/bff/reporter/start', () => {
      startCalls += 1;
      return HttpResponse.json({ csrfToken: issued });
    }),
    http.post('/api/bff/identity/pin/verify', ({ request }) => {
      seen.push({ path: '/api/bff/identity/pin/verify', csrf: request.headers.get('X-CSRF-Token') });
      return HttpResponse.json({ ok: true });
    }),
    http.post('/api/bff/reporter/x', ({ request }) => {
      seen.push({ path: '/api/bff/reporter/x', csrf: request.headers.get('X-CSRF-Token') });
      return HttpResponse.json({ ok: true });
    }),
  );
});
afterEach(() => resetBffToken());

describe('bffRequest', () => {
  it('asks for the token once and sends it on every write', async () => {
    await bffRequest('/api/bff/reporter/x', { method: 'POST', body: {} });
    await bffRequest('/api/bff/reporter/x', { method: 'POST', body: {} });
    expect(startCalls).toBe(1);
    expect(seen.map((r) => r.csrf)).toEqual(['T1', 'T1']);
  });

  it('does not ask for a token for a read', async () => {
    server.use(http.get('/api/bff/reporter/services', () => HttpResponse.json({ services: [] })));
    await bffRequest('/api/bff/reporter/services');
    expect(startCalls).toBe(0);
  });

  it('asks again after a PIN sign-in succeeded: the token it holds was the phone’s, the next write is the session’s', async () => {
    await bffRequest('/api/bff/identity/pin/verify', { method: 'POST', body: { pin: '123456' } });
    issued = 'T2';
    await bffRequest('/api/bff/reporter/x', { method: 'POST', body: {} });
    expect(startCalls).toBe(2);
    expect(seen.at(-1)?.csrf).toBe('T2');
  });

  it('keeps the token after a PIN that was wrong', async () => {
    server.use(http.post('/api/bff/identity/pin/verify', () => HttpResponse.json({ ok: false, triesLeft: 3 })));
    await bffRequest('/api/bff/identity/pin/verify', { method: 'POST', body: { pin: '123456' } });
    await bffRequest('/api/bff/reporter/x', { method: 'POST', body: {} });
    expect(startCalls).toBe(1);
  });

  it('refreshes the token once and repeats the write when it is refused as stale, and not a second time', async () => {
    let first = true;
    server.use(
      http.post('/api/bff/reporter/x', ({ request }) => {
        seen.push({ path: '/api/bff/reporter/x', csrf: request.headers.get('X-CSRF-Token') });
        if (first) {
          first = false;
          issued = 'T2';
          return HttpResponse.json({ code: 'csrf' }, { status: 403 });
        }
        return HttpResponse.json({ ok: true });
      }),
    );
    const reply = await bffRequest('/api/bff/reporter/x', { method: 'POST', body: {} });
    expect(reply.status).toBe(200);
    expect(seen.map((r) => r.csrf)).toEqual(['T1', 'T2']);
    server.use(http.post('/api/bff/reporter/x', () => HttpResponse.json({ code: 'csrf' }, { status: 403 })));
    expect((await bffRequest('/api/bff/reporter/x', { method: 'POST', body: {} })).status).toBe(403);
  });

  it('sends the Idempotency-Key a screen gives and nothing else it was not given', async () => {
    let key: string | null = null;
    server.use(http.post('/api/bff/reporter/x', ({ request }) => ((key = request.headers.get('Idempotency-Key')), HttpResponse.json({ ok: true }))));
    await bffRequest('/api/bff/reporter/x', { method: 'POST', body: {}, headers: { 'Idempotency-Key': 'screen-key-0001' } });
    expect(key).toBe('screen-key-0001');
  });

  it('answers status 0 and no body when the network fails', async () => {
    server.use(http.get('/api/bff/reporter/services', () => HttpResponse.error()));
    expect(await bffRequest('/api/bff/reporter/services')).toEqual({ status: 0, body: undefined });
  });
});
