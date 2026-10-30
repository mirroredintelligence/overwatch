// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { GET } from './route';

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

const URL_ = 'https://app.test/api/bff/lead/services/s-ucr-east';
const ctx = { params: Promise.resolve({ id: 's-ucr-east' }) };

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/lead/services/[id]', () => {
  it('answers the service name, and no suspension state it cannot read', async () => {
    server.use(
      http.get(`${BACKEND_BASE}/HealthcareService/s-ucr-east`, () =>
        HttpResponse.json({ resourceType: 'HealthcareService', id: 's-ucr-east', name: 'UCR East', active: true }),
      ),
    );
    const response = await GET(await leadRequest(URL_, 'lead'), ctx);
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ name: 'UCR East' });
  });

  it('answers 403 to an advisor', async () => {
    expect((await GET(await leadRequest(URL_, 'advisor'), ctx)).status).toBe(403);
  });

  it('answers 404 when the back end does not know the service, with no detail', async () => {
    server.use(
      http.get(`${BACKEND_BASE}/HealthcareService/s-ucr-east`, () =>
        HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'not-found', diagnostics: 'no service s-ucr-east' }] }, { status: 404 }),
      ),
    );
    const response = await GET(await leadRequest(URL_, 'lead'), ctx);
    expect(response.status).toBe(404);
    expect(await response.text()).not.toContain('s-ucr-east');
  });
});
