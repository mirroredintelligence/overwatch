// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as catchAll from '@/app/webhooks/[[...rest]]/route';
import * as reply from '@/app/webhooks/sms/twilio/route';
import * as status from '@/app/webhooks/sms/twilio/status/route';
import { server } from '@/test/msw/server';
import { MAX_FORM_BYTES, MAX_ANSWER_BYTES, TIMEOUT_MS } from './forward';

// The Twilio webhook forward (DEC-1302). `web` is the only app the internet reaches; Twilio calls it, and
// it passes the exact bytes of the form and the signature to the API, which checks the signature and finds
// the tenant from the number called. These tests use the back end's real answers (an empty TwiML 200, the
// fixed 403 body, a 500) and look at every byte and header the back end is sent.

const BACKEND = 'http://backend.test';
const REPLY_URL = `${BACKEND}/webhooks/sms/twilio`;
const STATUS_URL = `${BACKEND}/webhooks/sms/twilio/status`;
const PUBLIC = 'https://overwatch.mirroredintelligence.com';

const TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response/>';
const SIGNATURE = 'SampleSignature+/AbC123=';
const FORM_TYPE = 'application/x-www-form-urlencoded';

// A form with a plus, an encoded plus, an ampersand inside a value, raw (unencoded) unicode, an emoji and a
// trailing newline: anything that decoding and re-encoding would change.
const RAW_FORM =
  'MessageSid=SM0000000000000000000000000000000a&AccountSid=AC0000000000000000000000000000000a' +
  '&From=%2B447700900123&To=+447700900456&Body=a+b%2Bc%26d%3D1 café \u{1f642} x&Odd=%zz%\n';
const RAW_BYTES = new Uint8Array(Buffer.from(RAW_FORM, 'utf8'));

type Seen = { url: string; method: string; headers: Record<string, string>; body: Uint8Array };
type Route = typeof reply;

const ROUTES: { name: string; route: Route; path: string; url: string }[] = [
  { name: 'the reply route', route: reply, path: '/webhooks/sms/twilio', url: REPLY_URL },
  { name: 'the status route', route: status, path: '/webhooks/sms/twilio/status', url: STATUS_URL },
];

let seen: Seen[] = [];

function stub(url: string, answer: () => Response | Promise<Response> = () => new HttpResponse(TWIML, { status: 200, headers: { 'Content-Type': 'text/xml' } })) {
  server.use(
    http.post(url, async ({ request }) => {
      seen.push({
        url: request.url,
        method: request.method,
        headers: Object.fromEntries(request.headers.entries()),
        body: new Uint8Array(await request.arrayBuffer()),
      });
      return answer();
    }),
  );
}

function twilioRequest(path: string, init: { body?: BodyInit | null; headers?: Record<string, string>; query?: string } = {}): Request {
  const headers = new Headers({ 'Content-Type': FORM_TYPE, 'X-Twilio-Signature': SIGNATURE });
  for (const [name, value] of Object.entries(init.headers ?? {})) headers.set(name, value);
  return new Request(`${PUBLIC}${path}${init.query ?? ''}`, { method: 'POST', headers, body: init.body === undefined ? RAW_BYTES : init.body });
}

const logs = ['log', 'info', 'warn', 'error', 'debug'] as const;
let logged: string[] = [];

beforeEach(() => {
  seen = [];
  logged = [];
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND}/fhir`);
  for (const level of logs) {
    vi.spyOn(console, level).mockImplementation((...args: unknown[]) => {
      logged.push(args.map(String).join(' '));
    });
  }
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

describe.each(ROUTES)('$name', ({ route, path, url }) => {
  describe('what is forwarded', () => {
    it('sends the identical bytes of the form: nothing parsed, decoded or encoded again', async () => {
      stub(url);
      const response = await route.POST(twilioRequest(path));
      expect(response.status).toBe(200);
      expect(seen).toHaveLength(1);
      expect(Buffer.from(seen[0]!.body).equals(Buffer.from(RAW_BYTES))).toBe(true);
      expect(Buffer.from(seen[0]!.body).toString('utf8').endsWith('%zz%\n')).toBe(true);
    });

    it('sends bytes that are not text at all as they came', async () => {
      stub(url);
      const bytes = new Uint8Array([0x41, 0x3d, 0xff, 0xfe, 0x00, 0x26, 0x42, 0x3d, 0x0a, 0x0d]);
      await route.POST(twilioRequest(path, { body: bytes }));
      expect(Buffer.from(seen[0]!.body).equals(Buffer.from(bytes))).toBe(true);
    });

    it('calls the fixed path of the back end with POST, whatever the request was addressed to', async () => {
      stub(url);
      await route.POST(twilioRequest(path));
      expect(seen[0]!.method).toBe('POST');
      expect(new URL(seen[0]!.url).pathname).toBe(path);
      expect(new URL(seen[0]!.url).origin).toBe(BACKEND);
    });

    it('does not forward the query string', async () => {
      stub(url);
      await route.POST(twilioRequest(path, { query: '?tenant=trust-b&AccountSid=ACx&x=1' }));
      expect(seen).toHaveLength(1);
      expect(new URL(seen[0]!.url).search).toBe('');
    });

    it('sends the Content-Type and the signature exactly as received', async () => {
      stub(url);
      await route.POST(twilioRequest(path, { headers: { 'Content-Type': `${FORM_TYPE}; charset=UTF-8`, 'X-Twilio-Signature': SIGNATURE } }));
      expect(seen[0]!.headers['content-type']).toBe(`${FORM_TYPE}; charset=UTF-8`);
      expect(seen[0]!.headers['x-twilio-signature']).toBe(SIGNATURE);
    });

    it('sends no other request header of the caller: no cookie, no Authorization, no X-Forwarded-*, no host', async () => {
      stub(url);
      await route.POST(
        twilioRequest(path, {
          headers: {
            Cookie: 'diucs_session=abc; link_csrf=def',
            Authorization: 'Bearer sample-token',
            'X-Forwarded-For': '203.0.113.9',
            'X-Forwarded-Host': 'overwatch.mirroredintelligence.com',
            'X-Forwarded-Proto': 'https',
            Forwarded: 'for=203.0.113.9;host=overwatch.mirroredintelligence.com',
            'X-Real-IP': '203.0.113.9',
            'X-Edge-Auth': 'sample-edge',
            'CF-Connecting-IP': '203.0.113.9',
            'X-Tenant-Id': 'trust-b',
            'X-CSRF-Token': 'sample-csrf',
            'X-Screen-Secret': 'sample-screen',
            Origin: PUBLIC,
            Referer: `${PUBLIC}/x`,
            'Traceparent': '00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01',
            'I-Am-A-Strange-Header': 'x',
          },
        }),
      );
      const names = Object.keys(seen[0]!.headers).sort();
      // Only the two headers of the brief, and the ones the HTTP client itself adds to every request.
      const CLIENT_OWN = new Set(['accept', 'accept-encoding', 'accept-language', 'connection', 'content-length', 'sec-fetch-mode', 'user-agent']);
      expect(names.filter((n) => !CLIENT_OWN.has(n))).toEqual(['content-type', 'x-twilio-signature']);
      expect(seen[0]!.body.length).toBe(RAW_BYTES.length);
      // The host is the back end's own: it was not overridden with the public one.
      expect(seen[0]!.headers.host ?? new URL(seen[0]!.url).host).toBe('backend.test');
    });

    it('sends a request with no signature on, for the back end to refuse, and still sends the type', async () => {
      stub(url, () => new HttpResponse('Forbidden', { status: 403, headers: { 'Content-Type': 'text/plain' } }));
      const request = twilioRequest(path);
      request.headers.delete('X-Twilio-Signature');
      const response = await route.POST(request);
      expect(response.status).toBe(403);
      expect(seen[0]!.headers['x-twilio-signature']).toBeUndefined();
      expect(seen[0]!.headers['content-type']).toBe(FORM_TYPE);
    });

    it('refuses a request with no Content-Type, with an empty 400, and does not call the back end', async () => {
      stub(url);
      const request = new Request(`${PUBLIC}${path}`, { method: 'POST', headers: { 'X-Twilio-Signature': SIGNATURE }, body: new Uint8Array([0x41]) });
      request.headers.delete('Content-Type');
      const bare = new Request(`${PUBLIC}${path}`, { method: 'POST', headers: { 'X-Twilio-Signature': SIGNATURE } });
      for (const candidate of [request, bare]) {
        const response = await route.POST(candidate);
        expect(response.status).toBe(400);
        expect(await response.text()).toBe('');
      }
      expect(seen).toEqual([]);
    });
  });

  describe('what is answered', () => {
    it('answers the back end’s empty TwiML 200 with its status, body and type, and no-store', async () => {
      stub(url);
      const response = await route.POST(twilioRequest(path));
      expect(response.status).toBe(200);
      expect(await response.text()).toBe(TWIML);
      expect(response.headers.get('content-type')).toBe('text/xml');
      expect(response.headers.get('cache-control')).toBe('no-store');
    });

    it('answers the back end’s 403 with its fixed body as it is (a refusal tells a caller nothing more)', async () => {
      stub(url, () => new HttpResponse('Forbidden', { status: 403, headers: { 'Content-Type': 'text/plain' } }));
      const response = await route.POST(twilioRequest(path));
      expect(response.status).toBe(403);
      expect(await response.text()).toBe('Forbidden');
      expect(response.headers.get('content-type')).toBe('text/plain');
      expect(response.headers.get('cache-control')).toBe('no-store');
    });

    it('answers the back end’s 500 unchanged, so Twilio retries and the retry is not taken for a replay', async () => {
      stub(url, () => new HttpResponse('Internal Server Error', { status: 500, headers: { 'Content-Type': 'text/plain; charset=utf-8' } }));
      const response = await route.POST(twilioRequest(path));
      expect(response.status).toBe(500);
      expect(await response.text()).toBe('Internal Server Error');
      expect(response.headers.get('content-type')).toBe('text/plain; charset=utf-8');
    });

    it('passes on the Content-Type as received, and none when there was none', async () => {
      stub(url, () => new HttpResponse(null, { status: 200 }));
      const response = await route.POST(twilioRequest(path));
      expect(response.status).toBe(200);
      expect(response.headers.get('content-type')).toBeNull();
      expect(response.headers.get('cache-control')).toBe('no-store');
    });

    it('passes on no other header of the back end', async () => {
      stub(url, () => new HttpResponse(TWIML, { status: 200, headers: { 'Content-Type': 'text/xml', 'Set-Cookie': 'a=b; Path=/never', 'X-Powered-By': 'x', Location: '/x', 'Cache-Control': 'public, max-age=600' } }));
      const response = await route.POST(twilioRequest(path));
      expect(response.headers.get('set-cookie')).toBeNull();
      expect(response.headers.get('x-powered-by')).toBeNull();
      expect(response.headers.get('location')).toBeNull();
      expect(response.headers.get('cache-control')).toBe('no-store');
    });

    it('answers a status with no body (204) with no body', async () => {
      stub(url, () => new HttpResponse(null, { status: 204 }));
      const response = await route.POST(twilioRequest(path));
      expect(response.status).toBe(204);
      expect(await response.text()).toBe('');
    });
  });

  describe('what is refused or fails', () => {
    it('refuses a form of 64 KiB plus one byte, by its declared length, without calling the back end', async () => {
      stub(url);
      const body = new Uint8Array(MAX_FORM_BYTES + 1).fill(0x61);
      const response = await route.POST(twilioRequest(path, { body, headers: { 'Content-Length': String(body.length) } }));
      expect(response.status).toBe(413);
      expect(await response.text()).toBe('');
      expect(seen).toEqual([]);
    });

    it('refuses one whose body is over 64 KiB although it declared less, or nothing', async () => {
      stub(url);
      const body = new Uint8Array(MAX_FORM_BYTES + 1).fill(0x61);
      const lying = await route.POST(twilioRequest(path, { body, headers: { 'Content-Length': '12' } }));
      expect(lying.status).toBe(413);
      const chunked = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(body.slice(0, 40_000));
          controller.enqueue(body.slice(40_000));
          controller.close();
        },
      });
      const streamed = new Request(`${PUBLIC}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': FORM_TYPE },
        body: chunked,
        duplex: 'half',
      } as RequestInit);
      const unknown = await route.POST(streamed);
      expect(unknown.status).toBe(413);
      expect(seen).toEqual([]);
    });

    it('stops reading a body that never ends once it is over the limit', async () => {
      stub(url);
      let pulled = 0;
      const endless = new ReadableStream<Uint8Array>({
        pull(controller) {
          pulled += 1;
          controller.enqueue(new Uint8Array(16 * 1024).fill(0x61));
          if (pulled > 1000) controller.close();
        },
      });
      const request = new Request(`${PUBLIC}${path}`, { method: 'POST', headers: { 'Content-Type': FORM_TYPE }, body: endless, duplex: 'half' } as RequestInit);
      const response = await route.POST(request);
      expect(response.status).toBe(413);
      expect(pulled).toBeLessThan(20);
    });

    it('forwards a form of exactly 64 KiB', async () => {
      stub(url);
      const body = new Uint8Array(MAX_FORM_BYTES).fill(0x61);
      const response = await route.POST(twilioRequest(path, { body }));
      expect(response.status).toBe(200);
      expect(seen[0]!.body.length).toBe(MAX_FORM_BYTES);
    });

    it.each([301, 302, 303, 307, 308])('refuses a redirect (%i) from the back end: 502, empty, and the Location is not followed', async (code) => {
      let followed = 0;
      stub(url, () => new HttpResponse(null, { status: code, headers: { Location: `${BACKEND}/elsewhere` } }));
      server.use(
        http.all(`${BACKEND}/elsewhere`, () => {
          followed += 1;
          return new HttpResponse('followed');
        }),
      );
      const response = await route.POST(twilioRequest(path));
      expect(response.status).toBe(502);
      expect(await response.text()).toBe('');
      expect(response.headers.get('location')).toBeNull();
      expect(response.headers.get('cache-control')).toBe('no-store');
      expect(followed).toBe(0);
    });

    it('answers 502 with an empty body when the back end cannot be reached', async () => {
      server.use(http.post(url, () => HttpResponse.error()));
      const response = await route.POST(twilioRequest(path));
      expect(response.status).toBe(502);
      expect(await response.text()).toBe('');
      expect(response.headers.get('cache-control')).toBe('no-store');
    });

    it('answers 502 when the back end takes longer than 10 seconds', async () => {
      expect(TIMEOUT_MS).toBe(10_000);
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
      server.use(http.post(url, () => new Promise<Response>(() => undefined)));
      const pending = route.POST(twilioRequest(path));
      await vi.advanceTimersByTimeAsync(TIMEOUT_MS + 1);
      const response = await pending;
      expect(response.status).toBe(502);
      expect(await response.text()).toBe('');
    });

    it('answers 502 when the back end’s answer is over 64 KiB', async () => {
      stub(url, () => new HttpResponse(new Uint8Array(MAX_ANSWER_BYTES + 1).fill(0x61), { status: 200, headers: { 'Content-Type': 'text/plain' } }));
      const response = await route.POST(twilioRequest(path));
      expect(response.status).toBe(502);
      expect(await response.text()).toBe('');
    });

    it('answers an answer of exactly 64 KiB', async () => {
      stub(url, () => new HttpResponse(new Uint8Array(MAX_ANSWER_BYTES).fill(0x61), { status: 200, headers: { 'Content-Type': 'text/plain' } }));
      const response = await route.POST(twilioRequest(path));
      expect(response.status).toBe(200);
      expect((await response.arrayBuffer()).byteLength).toBe(MAX_ANSWER_BYTES);
    });

    it('answers 500 with an empty body, and calls nothing, when the back end address is not set', async () => {
      stub(url);
      vi.stubEnv('DIUCS_FHIR_BASE_URL', '');
      const response = await route.POST(twilioRequest(path));
      expect(response.status).toBe(500);
      expect(await response.text()).toBe('');
      expect(seen).toEqual([]);
    });
  });

  describe('what it will not do', () => {
    it.each(['GET', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'] as const)('answers %s with an empty 404, and does not call the back end', async (method) => {
      stub(url);
      const handler = route[method];
      expect(typeof handler).toBe('function');
      const response = await handler(new Request(`${PUBLIC}${path}`, { method }));
      expect(response.status).toBe(404);
      expect(await response.text()).toBe('');
      expect(seen).toEqual([]);
    });

    it('exports POST and the six other methods, and nothing else but the dynamic setting', () => {
      expect(Object.keys(route).sort()).toEqual(['DELETE', 'GET', 'HEAD', 'OPTIONS', 'PATCH', 'POST', 'PUT', 'dynamic']);
      expect(route.dynamic).toBe('force-dynamic');
    });

    it('logs only its path and the status, and never the body, the signature, a number or a text', async () => {
      stub(url, () => new HttpResponse('Forbidden', { status: 403, headers: { 'Content-Type': 'text/plain' } }));
      await route.POST(twilioRequest(path));
      server.use(http.post(url, () => HttpResponse.error()));
      await route.POST(twilioRequest(path));
      vi.stubEnv('DIUCS_FHIR_BASE_URL', '');
      await route.POST(twilioRequest(path));
      expect(logged.length).toBeGreaterThan(0);
      const all = logged.join('\n');
      for (const secret of [SIGNATURE, '447700900123', '447700900456', 'MessageSid', 'AccountSid', 'café', 'a+b', 'backend.test', 'Forbidden', 'sample']) {
        expect(all, secret).not.toContain(secret);
      }
      for (const line of logged) expect(line, line).toMatch(new RegExp(`^[a-z ]*: path=${path.replace(/\//g, '\\/')} status=\\d{3}$`));
    });

    it('logs nothing for an answer that went well', async () => {
      stub(url);
      await route.POST(twilioRequest(path));
      expect(logged).toEqual([]);
    });
  });
});

describe('every other path under /webhooks', () => {
  it.each(['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'] as const)('answers %s with an empty 404, and calls nothing', async (method) => {
    let called = 0;
    server.use(http.all(`${BACKEND}/*`, () => {
      called += 1;
      return new HttpResponse(TWIML);
    }));
    const response = await catchAll[method](new Request(`${PUBLIC}/webhooks/sms/other`, { method, body: method === 'POST' || method === 'PUT' || method === 'PATCH' || method === 'DELETE' ? RAW_BYTES : undefined, headers: { 'Content-Type': FORM_TYPE } }));
    expect(response.status).toBe(404);
    expect(await response.text()).toBe('');
    expect(called).toBe(0);
  });

  it('exports the seven methods and the dynamic setting only', () => {
    expect(Object.keys(catchAll).sort()).toEqual(['DELETE', 'GET', 'HEAD', 'OPTIONS', 'PATCH', 'POST', 'PUT', 'dynamic']);
    expect(catchAll.dynamic).toBe('force-dynamic');
  });
});
