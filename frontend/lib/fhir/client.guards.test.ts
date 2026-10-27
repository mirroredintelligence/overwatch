import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { server } from '@/test/msw/server';
import { FhirError, fhirFetch } from './client';

// Guard tests for DEC-109. Each one pins a behaviour that the first W01
// tests did not check, so that a removed or changed guard fails a test.

const BASE = 'http://backend.test/fhir';
const FHIR_JSON = 'application/fhir+json; fhirVersion=4.3';

beforeEach(() => {
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BASE);
});

afterEach(() => {
  vi.unstubAllEnvs();
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

    const error = await failureOf(fhirFetch('/Patient/text'));

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

    const result = await fhirFetch<{ id: string }>('/Patient/g');

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

    await fhirFetch('/Task', { body: { resourceType: 'Task' } });

    expect(methods).toEqual(['POST']);
  });

  it('omits the Authorization header when no token is given', async () => {
    const seen: (string | null)[] = [];
    server.use(
      http.get(`${BASE}/Patient/noauth`, ({ request }) => {
        seen.push(request.headers.get('authorization'));
        return HttpResponse.json({ resourceType: 'Patient', id: 'noauth' });
      }),
    );

    await fhirFetch('/Patient/noauth');

    expect(seen).toEqual([null]);
  });

  it('sends a traceparent on a POST as well, generated when none is given', async () => {
    const seen: (string | null)[] = [];
    server.use(
      http.post(`${BASE}/Observation`, ({ request }) => {
        seen.push(request.headers.get('traceparent'));
        return HttpResponse.json({ resourceType: 'Observation', id: 'o1' }, { status: 201 });
      }),
    );

    await fhirFetch('/Observation', { method: 'POST', body: { resourceType: 'Observation' } });

    expect(seen[0]).toMatch(/^00-[0-9a-f]{32}-[0-9a-f]{16}-01$/);
  });

  it('returns etag undefined when the response has no ETag header', async () => {
    server.use(
      http.get(`${BASE}/Patient/noetag`, () => HttpResponse.json({ resourceType: 'Patient', id: 'noetag' })),
    );

    const result = await fhirFetch<{ id: string }>('/Patient/noetag');

    expect(result.etag).toBeUndefined();
    expect(result.data.id).toBe('noetag');
  });

  it('a 2xx with an empty body returns data undefined and does not fail', async () => {
    server.use(
      http.post(`${BASE}/Task/t2/$accept`, () => new HttpResponse(null, { status: 200 })),
    );

    const result = await fhirFetch<undefined>('/Task/t2/$accept', { method: 'POST' });

    expect(result.data).toBeUndefined();
  });
});
