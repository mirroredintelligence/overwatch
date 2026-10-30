// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { GET, POST } from './route';

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

const URL_ = 'https://app.test/api/bff/lead/invitations';
const KEY = 'invite-key-0001';
const BODY = { serviceId: 's-ucr-east', role: 'Duty manager', phone: '07700 900123', channel: 'text' };

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/lead/invitations', () => {
  it('sends $invite-reporter with the service as a reference, the role, the phone and the channel, and answers the ids and the last four digits only', async () => {
    let sent: { parameter: { name: string }[] } | undefined;
    server.use(
      http.post(`${BACKEND_BASE}/Task/$invite-reporter`, async ({ request }) => {
        sent = (await request.json()) as typeof sent;
        return HttpResponse.json(
          {
            resourceType: 'Parameters',
            parameter: [
              { name: 'numberEnding', valueString: '0123' },
              { name: 'invitationId', valueString: 'inv-3' },
              { name: 'registrationId', valueString: 'reg-3' },
              { name: 'expiresAt', valueDateTime: '2026-11-01T09:00:00Z' },
            ],
          },
          { status: 201 },
        );
      }),
    );
    const response = await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY, body: BODY }));
    expect(response.status).toBe(201);
    const text = await response.text();
    expect(JSON.parse(text)).toEqual({ invitationId: 'inv-3', numberEnding: '0123', expiresAt: '2026-11-01T09:00:00Z' });
    expect(text).not.toContain('07700');
    expect(sent?.parameter.map((p) => p.name)).toEqual(['service', 'role', 'mobile', 'suggestedChannel']);
  });

  it('answers 409 with the code not-in-pilot when the back end refuses a service outside the pilot', async () => {
    server.use(
      http.post(`${BACKEND_BASE}/Task/$invite-reporter`, () =>
        HttpResponse.json(
          { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'business-rule', diagnostics: 'Only services in the pilot can be invited' }] },
          { status: 409 },
        ),
      ),
    );
    const response = await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY, body: BODY }));
    expect(response.status).toBe(409);
    expect(await response.json()).toMatchObject({ code: 'not-in-pilot' });
  });

  it('answers 400 for a phone that is not a UK mobile, and does not call the back end', async () => {
    let called = false;
    server.use(http.post(`${BACKEND_BASE}/Task/$invite-reporter`, () => { called = true; return HttpResponse.json({}); }));
    const response = await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY, body: { ...BODY, phone: '0123' } }));
    expect(response.status).toBe(400);
    expect(called).toBe(false);
  });

  it('answers 403 to an advisor', async () => {
    expect((await POST(await leadRequest(URL_, 'advisor', { method: 'POST', csrf: true, key: KEY, body: BODY }))).status).toBe(403);
  });
});

describe('GET /api/bff/lead/invitations', () => {
  it('answers 501 until the back end lists the invitations, and never an empty list', async () => {
    const response = await GET(await leadRequest(URL_, 'lead'));
    expect(response.status).toBe(501);
  });
});
