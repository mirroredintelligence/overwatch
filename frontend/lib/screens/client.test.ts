import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { server } from '@/test/msw/server';
import { connectScreen, pollPairing, renewSession, ScreenClientError, startPairing } from './client';

// The browser's calls to the BFF's screen routes. Each answer is checked before the page uses it,
// and each failure is one of a few kinds, never the BFF's own words.

async function kindOf(promise: Promise<unknown>): Promise<ScreenClientError> {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(ScreenClientError);
    return error as ScreenClientError;
  }
  throw new Error('it did not fail');
}

describe('renewSession', () => {
  it('posts to the session route and is done on paired', async () => {
    let seen: Request | undefined;
    server.use(http.post('*/api/bff/screens/session', ({ request }) => ((seen = request), HttpResponse.json({ status: 'paired' }))));
    await expect(renewSession()).resolves.toBeUndefined();
    expect(seen?.method).toBe('POST');
    expect(seen?.credentials).toBe('same-origin');
    expect(new URL(seen!.url).search).toBe('');
  });

  it.each([
    [404, 'not-found'],
    [503, 'unavailable'],
    [500, 'unavailable'],
    [403, 'unavailable'],
  ])('is %i → %s', async (status, kind) => {
    server.use(http.post('*/api/bff/screens/session', () => HttpResponse.json({}, { status })));
    expect((await kindOf(renewSession())).kind).toBe(kind);
  });

  it('is unavailable when the answer is not paired, or the network fails', async () => {
    server.use(http.post('*/api/bff/screens/session', () => HttpResponse.json({ status: 'waiting' })));
    expect((await kindOf(renewSession())).kind).toBe('unavailable');
    server.use(http.post('*/api/bff/screens/session', () => HttpResponse.error()));
    expect((await kindOf(renewSession())).kind).toBe('unavailable');
  });
});

describe('startPairing', () => {
  it('posts with no body and no query, and returns the code, the id and the expiry', async () => {
    let seen: Request | undefined;
    server.use(
      http.post('*/api/bff/screens/pairing', async ({ request }) => {
        seen = request.clone();
        return HttpResponse.json({ pairingId: 'pairing-1', code: '482913', expiresAt: '2026-10-30T09:10:00Z' }, { status: 201 });
      }),
    );
    expect(await startPairing()).toEqual({ pairingId: 'pairing-1', code: '482913', expiresAt: '2026-10-30T09:10:00Z' });
    expect(await seen?.text()).toBe('');
    expect(new URL(seen!.url).search).toBe('');
  });

  it('is throttled with the wait the answer gives, in milliseconds, at most ten minutes, and none when it gives none or something else', async () => {
    for (const [header, expected] of [['600', 600_000], ['5', 5_000], ['99999', 600_000], ['soon', null], [null, null]] as const) {
      server.use(
        http.post('*/api/bff/screens/pairing', () =>
          HttpResponse.json({}, { status: 429, headers: header === null ? {} : { 'Retry-After': header } }),
        ),
      );
      const error = await kindOf(startPairing());
      expect(error).toMatchObject({ kind: 'throttled', retryAfterMs: expected });
    }
  });

  it.each([
    [404, 'not-found'],
    [503, 'unavailable'],
    [500, 'unavailable'],
  ])('is %i → %s', async (status, kind) => {
    server.use(http.post('*/api/bff/screens/pairing', () => HttpResponse.json({}, { status })));
    expect((await kindOf(startPairing())).kind).toBe(kind);
  });

  it.each([
    ['a code that is not six digits', { pairingId: 'p', code: '1234', expiresAt: '2026-10-30T09:10:00Z' }],
    ['no id', { code: '482913', expiresAt: '2026-10-30T09:10:00Z' }],
    ['an id that is not a plain id', { pairingId: 'a/b', code: '482913', expiresAt: '2026-10-30T09:10:00Z' }],
    ['an expiry that is not a date', { pairingId: 'p', code: '482913', expiresAt: 'x' }],
  ])('is unavailable when the answer holds %s', async (_name, body) => {
    server.use(http.post('*/api/bff/screens/pairing', () => HttpResponse.json(body, { status: 201 })));
    expect((await kindOf(startPairing())).kind).toBe('unavailable');
  });
});

describe('pollPairing', () => {
  it('reads the status for the id, encoded, with a plain GET', async () => {
    let seen: Request | undefined;
    server.use(http.get('*/api/bff/screens/pairing/:id', ({ request }) => ((seen = request), HttpResponse.json({ status: 'waiting' }))));
    expect(await pollPairing('pairing-1')).toBe('waiting');
    expect(new URL(seen!.url).pathname).toBe('/api/bff/screens/pairing/pairing-1');
    expect(seen?.method).toBe('GET');
  });

  it.each(['waiting', 'paired', 'expired', 'connecting'])('passes on %s', async (status) => {
    server.use(http.get('*/api/bff/screens/pairing/:id', () => HttpResponse.json({ status })));
    expect(await pollPairing('pairing-1')).toBe(status);
  });

  it('is unavailable for a status it does not know, and not-found, throttled and unavailable for 404, 429 and 5xx', async () => {
    server.use(http.get('*/api/bff/screens/pairing/:id', () => HttpResponse.json({ status: 'online' })));
    expect((await kindOf(pollPairing('pairing-1'))).kind).toBe('unavailable');
    for (const [status, kind] of [[404, 'not-found'], [429, 'throttled'], [503, 'unavailable']] as const) {
      server.use(http.get('*/api/bff/screens/pairing/:id', () => HttpResponse.json({}, { status })));
      expect((await kindOf(pollPairing('pairing-1'))).kind).toBe(kind);
    }
  });
});

describe('connectScreen', () => {
  const INPUT = { code: '482913', name: 'Control room', location: null };

  function backEnd(csrf = 'c'.repeat(43), reply: () => Response = () => HttpResponse.json({ name: 'Control room', status: 'online', connectedAt: '2026-10-30T09:00:00Z' }, { status: 201 })) {
    const seen: { csrf: string | null; body: unknown }[] = [];
    server.use(
      http.get('*/api/bff/session', () => HttpResponse.json({ role: 'lead', services: [], sub: 'stf-1', csrfToken: csrf })),
      http.post('*/api/bff/screens', async ({ request }) => {
        seen.push({ csrf: request.headers.get('x-csrf-token'), body: await request.json() });
        return reply();
      }),
    );
    return seen;
  }

  it('reads the CSRF token the session gives, sends it as the header, and posts the code, name and place only', async () => {
    const seen = backEnd();
    const result = await connectScreen({ code: '482913', name: 'Control room', location: 'Ward 4' });
    expect(result).toEqual({ name: 'Control room', status: 'online', connectedAt: '2026-10-30T09:00:00Z' });
    expect(seen).toEqual([{ csrf: 'c'.repeat(43), body: { code: '482913', name: 'Control room', location: 'Ward 4' } }]);
  });

  it('leaves the place out when there is none', async () => {
    const seen = backEnd();
    await connectScreen(INPUT);
    expect(seen[0]?.body).toEqual({ code: '482913', name: 'Control room' });
  });

  it('is unauthorised when there is no session to read a token from, and sends nothing', async () => {
    let posted = false;
    server.use(
      http.get('*/api/bff/session', () => HttpResponse.json({ code: 'no-session' }, { status: 401 })),
      http.post('*/api/bff/screens', () => ((posted = true), HttpResponse.json({}, { status: 201 }))),
    );
    expect((await kindOf(connectScreen(INPUT))).kind).toBe('unauthorised');
    expect(posted).toBe(false);
  });

  it.each([
    [404, { code: 'not-found' }, 'not-found'],
    [401, { code: 'no-session' }, 'unauthorised'],
    [403, { code: 'forbidden' }, 'unauthorised'],
    [429, { code: 'throttled' }, 'throttled'],
    [503, { code: 'unavailable' }, 'unavailable'],
    [500, { code: 'exception' }, 'unavailable'],
  ])('is %i → %s', async (status, body, kind) => {
    backEnd('c'.repeat(43), () => HttpResponse.json(body, { status }));
    expect((await kindOf(connectScreen(INPUT))).kind).toBe(kind);
  });

  it('is invalid, with the field and the words the BFF gives, for a 400 or 422, and only for a field it knows', async () => {
    backEnd('c'.repeat(43), () => HttpResponse.json({ code: 'invalid', field: 'name', message: 'Enter a name for the screen' }, { status: 400 }));
    expect(await kindOf(connectScreen(INPUT))).toMatchObject({ kind: 'invalid', field: 'name', detail: 'Enter a name for the screen' });
    backEnd('c'.repeat(43), () => HttpResponse.json({ code: 'invalid', field: 'tenant', message: 'x' }, { status: 422 }));
    expect(await kindOf(connectScreen(INPUT))).toMatchObject({ kind: 'invalid', field: undefined });
  });

  it('is unavailable when the answer is not a connected screen, or the network fails', async () => {
    backEnd('c'.repeat(43), () => HttpResponse.json({ name: 'x', status: 'offline' }, { status: 201 }));
    expect((await kindOf(connectScreen(INPUT))).kind).toBe('unavailable');
    server.use(http.post('*/api/bff/screens', () => HttpResponse.error()));
    expect((await kindOf(connectScreen(INPUT))).kind).toBe('unavailable');
  });
});
