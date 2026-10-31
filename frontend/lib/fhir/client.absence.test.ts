import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { server } from '@/test/msw/server';
import { FhirError, fhirFetch } from './client';

// DEC-109 item 8: optional headers are sent only when given, and a body-read
// failure is a 503 FhirError (DEC-109 item 5).

const BASE = 'http://backend.test/fhir';
const TEST_TOKEN = 'token-for-tests';

beforeEach(() => {
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BASE);
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('optional request headers are absent when not given (DEC-109 item 8)', () => {
  it('sends no Idempotency-Key when none is given', async () => {
    const seen: (string | null)[] = [];
    server.use(
      http.post(`${BASE}/Task/a1/$cancel`, ({ request }) => {
        seen.push(request.headers.get('idempotency-key'));
        return new HttpResponse(null, { status: 204 });
      }),
    );

    await fhirFetch<undefined>('/Task/a1/$cancel', { token: TEST_TOKEN, method: 'POST' });

    expect(seen).toEqual([null]);
  });

  it('sends no If-Match when none is given', async () => {
    const seen: (string | null)[] = [];
    server.use(
      http.get(`${BASE}/Task/a2`, ({ request }) => {
        seen.push(request.headers.get('if-match'));
        return HttpResponse.json({ resourceType: 'Task', id: 'a2' });
      }),
    );

    await fhirFetch('/Task/a2', { token: TEST_TOKEN });

    expect(seen).toEqual([null]);
  });

  it('sends no Content-Type on a GET, which has no body', async () => {
    const seen: (string | null)[] = [];
    server.use(
      http.get(`${BASE}/Task/a3`, ({ request }) => {
        seen.push(request.headers.get('content-type'));
        return HttpResponse.json({ resourceType: 'Task', id: 'a3' });
      }),
    );

    await fhirFetch('/Task/a3', { token: TEST_TOKEN });

    expect(seen).toEqual([null]);
  });

  // A POST or PUT names its body type even with no body: the back end answers 415 to one that does not
  // (BodyTypeMiddleware; WB4, test/backend-edge.ts).
  it('sends the FHIR Content-Type on a POST with no body', async () => {
    const seen: (string | null)[] = [];
    server.use(
      http.post(`${BASE}/Task/a3/$withdraw`, ({ request }) => {
        seen.push(request.headers.get('content-type'));
        return new HttpResponse(null, { status: 204 });
      }),
    );

    await fhirFetch<undefined>('/Task/a3/$withdraw', { token: TEST_TOKEN, method: 'POST' });

    expect(seen).toEqual(['application/fhir+json; fhirVersion=4.3']);
  });
});

describe('a body-read failure is a 503 FhirError (DEC-109 item 5)', () => {
  it('gives FhirError 503 transient when reading a 2xx body fails', async () => {
    server.use(
      http.get(`${BASE}/Patient/broken`, () => {
        const body = new ReadableStream<Uint8Array>({
          start(controller) {
            controller.error(new Error('stream reset'));
          },
        });
        return new HttpResponse(body, { status: 200, headers: { 'Content-Type': 'application/fhir+json' } });
      }),
    );

    const error = await fhirFetch('/Patient/broken', { token: TEST_TOKEN }).then(
      () => new Error('the request succeeded'),
      (failure: unknown) => failure,
    );

    expect(error).toBeInstanceOf(FhirError);
    expect((error as FhirError).status).toBe(503);
    expect((error as FhirError).outcome.issue[0].code).toBe('transient');
  });
});
