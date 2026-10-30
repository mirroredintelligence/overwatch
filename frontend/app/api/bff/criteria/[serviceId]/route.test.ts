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

// The criteria the owner sees (W30): the current version, any draft or waiting change, the overdue day
// and the shift lead. The owner, clinical lead and shift lead read it; the back end decides per service.

const ID = 'SVC-SAMPLE-1';
const url = `https://tenant-a.example.test/api/bff/criteria/${ID}`;
const ctx = (serviceId: string) => ({ params: Promise.resolve({ serviceId }) });
const CURRENT = {
  id: 'CRIT-3',
  version: 3,
  status: 'current',
  reviewBy: '2027-01-31',
  ageMin: 18,
  ageMax: null,
  accepts: [{ code: 'frailty', label: 'Frailty' }],
  excludes: [],
  districts: ['DT4'],
  changedOn: '2026-10-01T09:00:00Z',
  authorRole: 'Criteria owner',
};

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  resetSeen();
});

describe('GET /api/bff/criteria/[serviceId]', () => {
  it('reads the overview with the caller’s token and answers the current values, the waiting change and the shift lead', async () => {
    answerBackend('get', `/criteria/${ID}`, 200, {
      serviceId: ID,
      serviceName: 'Community nursing',
      current: CURRENT,
      draft: null,
      pending: { id: 'CRIT-4', version: 4, changeReason: 'Review', changedOn: '2026-10-30T09:00:00Z' },
      overdue: false,
      overdueSince: null,
      shiftLead: { label: 'Shift lead', phone: '01305 000111' },
      isOwner: true,
    });
    const response = await GET(await callerRequest(url, 'owner'), ctx(ID));
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({
      serviceName: 'Community nursing',
      current: { version: 3, reviewBy: '2027-01-31', accepts: ['frailty'], excludes: [], ageMin: 18, ageMax: null, districts: ['DT4'] },
      draft: { version: 4, status: 'waiting' },
      shiftLead: { role: 'Shift lead', phone: '01305 000111' },
    });
    expect(seen[0]).toMatchObject({ path: `/criteria/${ID}`, auth: 'Bearer backend-token-sample-value' });
  });

  it('answers 404 for a service the caller holds no criteria for, with the one not-found words', async () => {
    answerBackend('get', `/criteria/${ID}`, 404, { resourceType: 'OperationOutcome', issue: [] });
    const response = await GET(await callerRequest(url, 'owner'), ctx(ID));
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ code: 'not-found', message: 'We could not find that.' });
  });

  it('answers 503 when the back end answers criteria the page cannot read, and when it cannot be reached', async () => {
    answerBackend('get', `/criteria/${ID}`, 200, { serviceName: 'x' });
    expect((await GET(await callerRequest(url, 'owner'), ctx(ID))).status).toBe(503);
    breakBackend('get', `/criteria/${ID}`);
    expect((await GET(await callerRequest(url, 'owner'), ctx(ID))).status).toBe(503);
  });

  it('refuses the applicant and the advisor, without calling the back end', async () => {
    expect((await GET(await callerRequest(url, 'reporter'), ctx(ID))).status).toBe(403);
    expect((await GET(await callerRequest(url, 'advisor'), ctx(ID))).status).toBe(403);
    expect(seen).toHaveLength(0);
  });
});
