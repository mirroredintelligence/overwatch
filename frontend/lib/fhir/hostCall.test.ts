// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BACKEND_ROOT } from '@/test/fixtures/links';
import { server } from '@/test/msw/server';
import { BackendCallError, backendRoot, callBackend } from './hostCall';

const PING = `${BACKEND_ROOT}/public/ping`;

beforeEach(() => {
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
});

describe('backendRoot', () => {
  it('is the origin of the FHIR base URL', () => {
    expect(backendRoot('http://127.0.0.1:4010/fhir')).toBe('http://127.0.0.1:4010');
  });

  it('names the variable and never the value', () => {
    expect(() => backendRoot('https://api.example.test/other')).toThrow(/DIUCS_FHIR_BASE_URL/);
    expect(() => backendRoot(undefined)).toThrow(/DIUCS_FHIR_BASE_URL/);
  });
});

describe('callBackend', () => {
  it('sends the host it is given as the Host header, because the tenant is the host', async () => {
    let seen: string | null = null;
    server.use(http.get(PING, ({ request }) => {
      seen = request.headers.get('host');
      return HttpResponse.json({ ok: true });
    }));
    const reply = await callBackend({ method: 'GET', path: '/public/ping', host: 'tenant-a.example.test' });
    expect(reply).toMatchObject({ status: 200, body: { ok: true } });
    expect(seen).toBe('tenant-a.example.test');
  });

  it('sends no Authorization header and no tenant header of any kind', async () => {
    let names: string[] = [];
    server.use(http.post(PING, ({ request }) => {
      names = [...request.headers.keys()];
      return HttpResponse.json({});
    }));
    await callBackend({ method: 'POST', path: '/public/ping', host: 'tenant-a.example.test', body: { a: 1 } });
    expect(names).not.toContain('authorization');
    expect(names.filter((n) => /tenant|scope|network/.test(n))).toEqual([]);
  });

  it('sends a JSON body and reads a JSON answer', async () => {
    let body: unknown;
    server.use(http.post(PING, async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({ got: true }, { status: 201 });
    }));
    const reply = await callBackend({ method: 'POST', path: '/public/ping', host: 'a.test', body: { idToken: 'x' } });
    expect(body).toEqual({ idToken: 'x' });
    expect(reply).toMatchObject({ status: 201, body: { got: true } });
  });

  it.each(['a.test/evil', 'a b', '', 'a.test?x', 'user@a.test'])('refuses the host %j before any call', async (host) => {
    const seen = vi.fn();
    server.use(http.get(PING, () => {
      seen();
      return HttpResponse.json({});
    }));
    await expect(callBackend({ method: 'GET', path: '/public/ping', host })).rejects.toBeInstanceOf(BackendCallError);
    expect(seen).not.toHaveBeenCalled();
  });

  it('refuses a missing host', async () => {
    await expect(callBackend({ method: 'GET', path: '/public/ping', host: null })).rejects.toMatchObject({ kind: 'unavailable' });
  });

  it('answers a back end that cannot be reached as unavailable, without the network error', async () => {
    server.use(http.get(PING, () => HttpResponse.error()));
    const error = await callBackend({ method: 'GET', path: '/public/ping', host: 'a.test' }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(BackendCallError);
    expect((error as BackendCallError).kind).toBe('unavailable');
    expect((error as Error).message).not.toMatch(/backend\.test|ECONN/);
  });

  it('keeps the Retry-After of a limited answer and nothing else of the headers', async () => {
    server.use(http.get(PING, () => HttpResponse.json({}, { status: 429, headers: { 'Retry-After': '30', 'Set-Cookie': 'x=1' } })));
    const reply = await callBackend({ method: 'GET', path: '/public/ping', host: 'a.test' });
    expect(reply).toEqual({ status: 429, body: {}, retryAfter: '30' });
  });

  it('does not read more than the limit of an answer', async () => {
    server.use(http.get(PING, () => new HttpResponse('x'.repeat(200_000))));
    const reply = await callBackend({ method: 'GET', path: '/public/ping', host: 'a.test' });
    expect(reply.body).toBeUndefined();
  });
});
