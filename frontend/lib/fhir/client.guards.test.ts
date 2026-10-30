import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { server } from '@/test/msw/server';
import { FhirError, fhirFetch, fhirStream, TokenRequired } from './client';

// Guard tests for DEC-109. Each one pins a behaviour that the first W01
// tests did not check, so that a removed or changed guard fails a test.

const BASE = 'http://backend.test/fhir';
const TEST_TOKEN = 'token-for-tests';
const FHIR_JSON = 'application/fhir+json; fhirVersion=4.3';

beforeEach(() => {
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BASE);
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

async function failureOf(promise: Promise<unknown>): Promise<unknown> {
  return promise.then(
    () => {
      throw new Error('expected the request to fail, but it succeeded');
    },
    (error: unknown) => error,
  );
}

describe('fhirFetch guards (DEC-109)', () => {
  it('a 2xx body that is not JSON is a 502 FhirError, not returned as data', async () => {
    server.use(
      http.get(`${BASE}/Patient/text`, () =>
        HttpResponse.text('this is not json', { status: 200, headers: { 'Content-Type': FHIR_JSON } }),
      ),
    );

    const error = await failureOf(fhirFetch('/Patient/text', { token: TEST_TOKEN }));

    expect(error).toBeInstanceOf(FhirError);
    expect((error as FhirError).status).toBe(502);
    expect((error as FhirError).outcome.issue[0].code).toBe('exception');
  });

  it('defaults the method to GET when no body is given', async () => {
    const methods: string[] = [];
    server.use(
      http.get(`${BASE}/Patient/g`, ({ request }) => {
        methods.push(request.method);
        return HttpResponse.json({ resourceType: 'Patient', id: 'g' });
      }),
    );

    const result = await fhirFetch<{ id: string }>('/Patient/g', { token: TEST_TOKEN });

    expect(methods).toEqual(['GET']);
    expect(result.data.id).toBe('g');
  });

  it('defaults the method to POST when a body is given and no method is named', async () => {
    const methods: string[] = [];
    server.use(
      http.post(`${BASE}/Task`, ({ request }) => {
        methods.push(request.method);
        return HttpResponse.json({ resourceType: 'Task', id: 't1' }, { status: 201 });
      }),
    );

    await fhirFetch('/Task', { token: TEST_TOKEN, body: { resourceType: 'Task' } });

    expect(methods).toEqual(['POST']);
  });

  it('sends a traceparent on a POST as well, generated when none is given', async () => {
    const seen: (string | null)[] = [];
    server.use(
      http.post(`${BASE}/Observation`, ({ request }) => {
        seen.push(request.headers.get('traceparent'));
        return HttpResponse.json({ resourceType: 'Observation', id: 'o1' }, { status: 201 });
      }),
    );

    await fhirFetch('/Observation', { token: TEST_TOKEN, method: 'POST', body: { resourceType: 'Observation' } });

    expect(seen[0]).toMatch(/^00-[0-9a-f]{32}-[0-9a-f]{16}-01$/);
  });

  it('returns etag undefined when the response has no ETag header', async () => {
    server.use(
      http.get(`${BASE}/Patient/noetag`, () => HttpResponse.json({ resourceType: 'Patient', id: 'noetag' })),
    );

    const result = await fhirFetch<{ id: string }>('/Patient/noetag', { token: TEST_TOKEN });

    expect(result.etag).toBeUndefined();
    expect(result.data.id).toBe('noetag');
  });

  it('a 2xx with an empty body returns data undefined and does not fail', async () => {
    server.use(
      http.post(`${BASE}/Task/t2/$accept`, () => new HttpResponse(null, { status: 200 })),
    );

    const result = await fhirFetch<undefined>('/Task/t2/$accept', { token: TEST_TOKEN, method: 'POST' });

    expect(result.data).toBeUndefined();
  });
});


// TEN-045 (audit D 7.1, 3.7): the one place the front end calls the back end with a bearer token keeps
// the tenant out of every request it can influence, never lets a cache keep an answer, and does not
// run without a token.
describe('a token is required (TEN-045)', () => {
  it.each([
    ['none', undefined],
    ['empty', ''],
    ['blank', '   '],
    ['not text', 7],
    ['with a space', 'Bearer abc'],
    ['with a newline', 'abc\ndef'],
    ['too long', 'a'.repeat(9000)],
  ])('refuses a call with a token that is %s, and sends nothing', async (_name, token) => {
    const seen = vi.fn();
    server.use(http.get(`${BASE}/Patient/x`, () => { seen(); return HttpResponse.json({}); }));
    await expect(fhirFetch('/Patient/x', { token: token as string })).rejects.toBeInstanceOf(TokenRequired);
    await expect(fhirStream('/events', { token: token as string })).rejects.toBeInstanceOf(TokenRequired);
    expect(seen).not.toHaveBeenCalled();
  });

  it('refuses a call with no init at all', async () => {
    await expect(fhirFetch('/Patient/x')).rejects.toBeInstanceOf(TokenRequired);
  });

  it('says so in a fixed message that holds no token', async () => {
    const error = await fhirFetch('/Patient/x', { token: 'a b' }).catch((e: unknown) => e);
    expect((error as Error).message).toBe('A back-end token is required for this call.');
  });

  it('sends the token it is given as the bearer, and no other authorization', async () => {
    const seen: (string | null)[] = [];
    server.use(http.get(`${BASE}/Patient/b`, ({ request }) => { seen.push(request.headers.get('authorization')); return HttpResponse.json({}); }));
    await fhirFetch('/Patient/b', { token: TEST_TOKEN });
    expect(seen).toEqual([`Bearer ${TEST_TOKEN}`]);
  });
});

describe('an answer is never stored (TEN-045)', () => {
  it('asks fetch not to use the cache, for a call and for a stream', async () => {
    const spy = vi.spyOn(globalThis, 'fetch');
    server.use(
      http.get(`${BASE}/Patient/c`, () => HttpResponse.json({})),
      http.get(`${BASE}/events`, () => new HttpResponse('', { headers: { 'Content-Type': 'text/event-stream' } })),
    );
    await fhirFetch('/Patient/c', { token: TEST_TOKEN });
    const stream = await fhirStream('/events', { token: TEST_TOKEN });
    await stream.body.cancel();
    const inits = spy.mock.calls.map(([, init]) => init as RequestInit | undefined);
    expect(inits).toHaveLength(2);
    for (const init of inits) expect(init?.cache).toBe('no-store');
  });

  it('sets no next.revalidate or next.tags on the request', async () => {
    const spy = vi.spyOn(globalThis, 'fetch');
    server.use(http.get(`${BASE}/Patient/d`, () => HttpResponse.json({})));
    await fhirFetch('/Patient/d', { token: TEST_TOKEN });
    expect(JSON.stringify(spy.mock.calls[0]?.[1])).not.toMatch(/revalidate|tags/);
  });
});

describe('no tenant is ever sent (TEN-045)', () => {
  const TENANT_LIKE = /tenant|scope|network|organi[sz]ation|source/i;

  it('sends no header that names a tenant, scope or network, and no header the caller adds', async () => {
    let names: string[] = [];
    server.use(http.post(`${BASE}/Task`, ({ request }) => { names = [...request.headers.keys()]; return HttpResponse.json({}, { status: 201 }); }));
    await fhirFetch('/Task', {
      token: TEST_TOKEN,
      body: { resourceType: 'Task' },
      idempotencyKey: 'k',
      ifMatch: 'W/"1"',
      // A caller cannot add a header: the type has no place for one, and a cast does not change that.
      ...({ headers: { 'X-Tenant-Id': 'trust-b', Host: 'tenant-b.example.test' }, tenant: 'trust-b' } as object),
    });
    expect(names.filter((n) => TENANT_LIKE.test(n))).toEqual([]);
    expect(names).not.toContain('host-override');
  });

  it('sends only the headers it sets itself', async () => {
    let names: string[] = [];
    server.use(http.get(`${BASE}/Patient/e`, ({ request }) => { names = [...request.headers.keys()]; return HttpResponse.json({}); }));
    await fhirFetch('/Patient/e', { token: TEST_TOKEN });
    const allowed = new Set(['accept', 'traceparent', 'authorization', 'idempotency-key', 'if-match', 'content-type', 'accept-language', 'accept-encoding', 'user-agent', 'connection', 'host', 'content-length', 'sec-fetch-mode', 'cache-control', 'pragma']);
    expect(names.filter((n) => !allowed.has(n))).toEqual([]);
  });

  it.each([
    '/Patient?tenant=trust-b',
    '/Patient?_count=5&tenantId=trust-b',
    '/Patient?Tenant_ID=trust-b',
    '/Patient?scope=network',
    '/Patient?network=net-x',
    '/Patient?%74enant=trust-b',
    '/Patient?x=1&source=trust-b',
    '/Patient?tenant.id=trust-b',
  ])('refuses the path %s, and sends nothing', async (path) => {
    const seen = vi.fn();
    server.use(http.get(`${BASE}/Patient`, () => { seen(); return HttpResponse.json({}); }));
    await expect(fhirFetch(path, { token: TEST_TOKEN })).rejects.toThrow(/path/i);
    await expect(fhirStream(path, { token: TEST_TOKEN })).rejects.toThrow(/path/i);
    expect(seen).not.toHaveBeenCalled();
  });

  it('lets an ordinary query through', async () => {
    const seen: string[] = [];
    server.use(http.get(`${BASE}/Observation`, ({ request }) => { seen.push(new URL(request.url).search); return HttpResponse.json({}); }));
    await fhirFetch('/Observation?_count=5&status=final', { token: TEST_TOKEN });
    expect(seen).toEqual(['?_count=5&status=final']);
  });

  it.each([
    '/../auth/token',
    '/Patient/../../auth/token',
    '/%2e%2e/auth/token',
    '/Patient/%2E%2E/x',
    '//evil.example/x',
    '/Patient\\x',
    'http://evil.example/x',
    '/Patient/x#frag',
    '/Patient\n/x',
    '',
  ])('refuses the path %j: it cannot leave the FHIR base', async (path) => {
    const seen = vi.fn();
    server.use(http.all('*', () => { seen(); return HttpResponse.json({}); }));
    await expect(fhirFetch(path, { token: TEST_TOKEN })).rejects.toThrow(/path/i);
    expect(seen).not.toHaveBeenCalled();
  });
});
