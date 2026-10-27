import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { server } from '@/test/msw/server';
import { FhirError, fhirFetch } from './client';
import type { OperationOutcome, Resource } from './types';

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

describe('fhirFetch', () => {
  it('GETs a resource with the FHIR Accept header and returns its data and ETag', async () => {
    const accepts: (string | null)[] = [];
    server.use(
      http.get(`${BASE}/HealthcareService/a1`, ({ request }) => {
        accepts.push(request.headers.get('accept'));
        return HttpResponse.json(
          { resourceType: 'HealthcareService', id: 'a1' },
          { headers: { 'Content-Type': FHIR_JSON, ETag: 'W/"2"' } },
        );
      }),
    );

    const result = await fhirFetch<Resource>('/HealthcareService/a1');

    expect(result.data.id).toBe('a1');
    expect(result.etag).toBe('W/"2"');
    expect(accepts).toEqual([FHIR_JSON]);
  });

  it('POSTs a JSON body with the token, idempotency key and If-Match headers', async () => {
    const seen: { headers: Headers; body: unknown }[] = [];
    server.use(
      http.post(`${BASE}/Task`, async ({ request }) => {
        seen.push({ headers: request.headers, body: await request.json() });
        return HttpResponse.json(
          { resourceType: 'Task', id: 't9' },
          { status: 201, headers: { 'Content-Type': FHIR_JSON, ETag: 'W/"4"' } },
        );
      }),
    );

    const result = await fhirFetch<Resource>('/Task', {
      method: 'POST',
      body: { resourceType: 'Task', status: 'requested' },
      token: 'tok-123',
      idempotencyKey: 'idem-1',
      ifMatch: 'W/"3"',
    });

    expect(seen).toHaveLength(1);
    expect(seen[0].headers.get('authorization')).toBe('Bearer tok-123');
    expect(seen[0].headers.get('idempotency-key')).toBe('idem-1');
    expect(seen[0].headers.get('if-match')).toBe('W/"3"');
    expect(seen[0].headers.get('content-type')).toBe(FHIR_JSON);
    expect(seen[0].body).toEqual({ resourceType: 'Task', status: 'requested' });
    expect(result.data.id).toBe('t9');
    expect(result.etag).toBe('W/"4"');
  });

  it('sends a generated W3C traceparent when the caller gives none', async () => {
    const seen: (string | null)[] = [];
    server.use(
      http.get(`${BASE}/Patient/x`, ({ request }) => {
        seen.push(request.headers.get('traceparent'));
        return HttpResponse.json({ resourceType: 'Patient', id: 'x' });
      }),
    );

    await fhirFetch<Resource>('/Patient/x');

    expect(seen[0]).toMatch(/^00-[0-9a-f]{32}-[0-9a-f]{16}-01$/);
  });

  it('passes a supplied traceparent through unchanged', async () => {
    const supplied = '00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01';
    const seen: (string | null)[] = [];
    server.use(
      http.get(`${BASE}/Patient/y`, ({ request }) => {
        seen.push(request.headers.get('traceparent'));
        return HttpResponse.json({ resourceType: 'Patient', id: 'y' });
      }),
    );

    await fhirFetch<Resource>('/Patient/y', { traceparent: supplied });

    expect(seen).toEqual([supplied]);
  });

  it('throws FhirError with the OperationOutcome from a 404 response', async () => {
    const outcome: OperationOutcome = {
      resourceType: 'OperationOutcome',
      issue: [{ severity: 'error', code: 'not-found', diagnostics: 'no such service' }],
    };
    server.use(
      http.get(`${BASE}/HealthcareService/missing`, () =>
        HttpResponse.json(outcome, { status: 404, headers: { 'Content-Type': FHIR_JSON } }),
      ),
    );

    const error = await failureOf(fhirFetch('/HealthcareService/missing'));

    expect(error).toBeInstanceOf(FhirError);
    expect((error as FhirError).status).toBe(404);
    expect((error as FhirError).outcome).toEqual(outcome);
  });

  it('synthesises an OperationOutcome when a 500 response has an HTML body', async () => {
    server.use(
      http.get(`${BASE}/Observation`, () =>
        HttpResponse.html('<html><body>internal password trace</body></html>', { status: 500 }),
      ),
    );

    const error = await failureOf(fhirFetch('/Observation'));

    expect(error).toBeInstanceOf(FhirError);
    expect((error as FhirError).status).toBe(500);
    expect((error as FhirError).outcome).toEqual({
      resourceType: 'OperationOutcome',
      issue: [{ severity: 'error', code: 'exception', diagnostics: 'HTTP 500' }],
    });
    expect(JSON.stringify((error as FhirError).outcome)).not.toContain('password');
  });

  it('throws FhirError 503 with a transient issue when the network request fails', async () => {
    server.use(http.get(`${BASE}/HealthcareService`, () => HttpResponse.error()));

    const error = await failureOf(fhirFetch('/HealthcareService'));

    expect(error).toBeInstanceOf(FhirError);
    expect((error as FhirError).status).toBe(503);
    expect((error as FhirError).outcome.issue[0].code).toBe('transient');
  });

  it('returns data undefined for a 204 response', async () => {
    server.use(
      http.post(`${BASE}/Task/t1/$cancel`, () => new HttpResponse(null, { status: 204 })),
    );

    const result = await fhirFetch<undefined>('/Task/t1/$cancel', { method: 'POST' });

    expect(result.data).toBeUndefined();
  });

  it('throws an error that names DIUCS_FHIR_BASE_URL when the variable is missing', async () => {
    vi.unstubAllEnvs();
    delete process.env.DIUCS_FHIR_BASE_URL;

    const error = await failureOf(fhirFetch('/HealthcareService'));

    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toContain('DIUCS_FHIR_BASE_URL');
  });

  it('treats an empty DIUCS_FHIR_BASE_URL as missing', async () => {
    vi.stubEnv('DIUCS_FHIR_BASE_URL', '');

    const error = await failureOf(fhirFetch('/HealthcareService'));

    expect((error as Error).message).toContain('DIUCS_FHIR_BASE_URL');
  });
});
