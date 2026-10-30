// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BACKEND_ROOT } from '@/test/fixtures/links';
import { answerBackend, breakBackend, resetSeen, seen } from '@/test/applicant/backend';
import { callerRequest } from '@/test/applicant/session';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { withApplicantHandlers } from '@/test/msw/applicant';
import { GET } from './route';

withApplicantHandlers();

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

// My services (W26): the applicant's own registrations from the back end's /my/registrations, with
// the state and the detail the screen words. A registration nobody has sent is not listed here.

const url = 'https://tenant-a.example.test/api/bff/registrations/mine';

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  resetSeen();
});

describe('GET /api/bff/registrations/mine', () => {
  it('reads my registrations with the bearer token and answers the rows the screen words', async () => {
    answerBackend('get', '/my/registrations', 200, {
      registrations: [
        { registrationId: 'REG-1', serviceId: 'SVC-1', serviceName: 'Community nursing', status: 'live', submittedAt: '2026-10-01T09:00:00Z' },
        { registrationId: 'REG-2', serviceId: 'SVC-2', serviceName: 'Virtual ward', status: 'draft', submittedAt: null },
      ],
    });
    const response = await GET(await callerRequest(url));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      services: [{ id: 'REG-1', serviceName: 'Community nursing', state: 'active', detail: 'Live' }],
    });
    expect(seen[0]).toMatchObject({ path: '/my/registrations', auth: 'Bearer backend-token-sample-value' });
  });

  it('answers 503 when the back end cannot be reached', async () => {
    breakBackend('get', '/my/registrations');
    const response = await GET(await callerRequest(url));
    expect(response.status).toBe(503);
  });

  it('refuses a lead', async () => {
    expect((await GET(await callerRequest(url, 'lead'))).status).toBe(403);
    expect(seen).toHaveLength(0);
  });
});
