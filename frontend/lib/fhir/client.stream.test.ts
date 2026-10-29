// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { readAll, streamOf } from '@/test/sse';
import { server } from '@/test/msw/server';
import { FhirError, fhirStream } from './client';

const BASE = 'http://backend.test/fhir';
const EVENTS = `${BASE}/events`;
const SSE = 'text/event-stream';

beforeEach(() => {
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BASE);
});

afterEach(() => {
  vi.unstubAllEnvs();
});

async function failureOf(promise: Promise<unknown>): Promise<FhirError> {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(FhirError);
    return error as FhirError;
  }
  throw new Error('expected the request to fail, but it succeeded');
}

describe('fhirStream', () => {
  it('opens a GET with the bearer token, asks for an event stream and sends a traceparent, and returns the body unread', async () => {
    let seen: Request | undefined;
    server.use(
      http.get(EVENTS, ({ request }) => {
        seen = request.clone();
        return new HttpResponse(streamOf(['event: board\ndata: {}\n\n']), { headers: { 'Content-Type': SSE } });
      }),
    );

    const { body } = await fhirStream('/events', { token: 'tok-1' });

    expect(seen?.method).toBe('GET');
    expect(seen?.headers.get('authorization')).toBe('Bearer tok-1');
    expect(seen?.headers.get('accept')).toBe(SSE);
    expect(seen?.headers.get('traceparent')).toMatch(/^00-[0-9a-f]{32}-[0-9a-f]{16}-0[01]$/);
    expect(new URL(seen?.url ?? '').search).toBe('');
    expect(await readAll(body)).toBe('event: board\ndata: {}\n\n');
  });

  it('passes a given traceparent through unchanged', async () => {
    let traceparent: string | null = null;
    server.use(
      http.get(EVENTS, ({ request }) => {
        traceparent = request.headers.get('traceparent');
        return new HttpResponse(streamOf([]), { headers: { 'Content-Type': SSE } });
      }),
    );
    const given = '00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01';

    await fhirStream('/events', { token: 't', traceparent: given });

    expect(traceparent).toBe(given);
  });

  it('accepts a content type with a charset', async () => {
    server.use(http.get(EVENTS, () => new HttpResponse(streamOf([]), { headers: { 'Content-Type': `${SSE}; charset=utf-8` } })));

    await expect(fhirStream('/events', { token: 't' })).resolves.toHaveProperty('body');
  });

  it.each([401, 403, 404, 500])('throws a FhirError with status %i for a refused or failed request', async (status) => {
    server.use(
      http.get(EVENTS, () =>
        HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'login' }] }, { status }),
      ),
    );

    const error = await failureOf(fhirStream('/events', { token: 't' }));

    expect(error.status).toBe(status);
    expect(error.outcome.issue?.[0]?.code).toBe('login');
  });

  it('throws a 503 FhirError, with no detail, when the back end cannot be reached', async () => {
    server.use(http.get(EVENTS, () => HttpResponse.error()));

    const error = await failureOf(fhirStream('/events', { token: 't' }));

    expect(error.status).toBe(503);
    expect(JSON.stringify(error.outcome)).not.toContain('backend.test');
  });

  it('throws a 502 FhirError when a 200 is not an event stream, rather than relaying something else', async () => {
    server.use(http.get(EVENTS, () => HttpResponse.json({ resourceType: 'Parameters' })));

    expect((await failureOf(fhirStream('/events', { token: 't' }))).status).toBe(502);
  });

  it('throws a 502 FhirError when a 200 has no body', async () => {
    server.use(http.get(EVENTS, () => new HttpResponse(null, { status: 200, headers: { 'Content-Type': SSE } })));

    expect((await failureOf(fhirStream('/events', { token: 't' }))).status).toBe(502);
  });

  it('stops the request when its signal is aborted', async () => {
    let upstreamAborted = false;
    server.use(
      http.get(EVENTS, ({ request }) => {
        request.signal.addEventListener('abort', () => (upstreamAborted = true));
        return new HttpResponse(streamOf(['event: board\ndata: {}\n\n'], { hold: true }), { headers: { 'Content-Type': SSE } });
      }),
    );
    const controller = new AbortController();
    const { body } = await fhirStream('/events', { token: 't', signal: controller.signal });
    await body.getReader().read();

    controller.abort();

    await vi.waitFor(() => expect(upstreamAborted).toBe(true));
  });

  it('fails, naming the variable only, when the base URL is not set', async () => {
    vi.stubEnv('DIUCS_FHIR_BASE_URL', '');

    await expect(fhirStream('/events', { token: 't' })).rejects.toThrow(/DIUCS_FHIR_BASE_URL/);
  });
});
