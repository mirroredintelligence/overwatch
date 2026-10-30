// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BACKEND_ROOT } from '@/test/fixtures/links';
import { answerBackend, resetSeen, seen } from '@/test/applicant/backend';
import { callerRequest } from '@/test/applicant/session';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { withApplicantHandlers } from '@/test/msw/applicant';
import { GET } from './route';

withApplicantHandlers();

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

// The change waiting for the second approval, as the approver reads it (W31). The author's name is
// never in it: the author is a role, and isAuthor says whether the caller wrote it.

const ID = 'SVC-SAMPLE-1';
const url = `https://tenant-a.example.test/api/bff/criteria/${ID}/pending`;
const ctx = (serviceId: string) => ({ params: Promise.resolve({ serviceId }) });

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  resetSeen();
});

describe('GET /api/bff/criteria/[serviceId]/pending', () => {
  it('reads the waiting change and answers its words, reason, author role and whether the approver wrote it', async () => {
    answerBackend('get', `/criteria/${ID}/pending`, 200, {
      criteriaId: 'CRIT-5',
      serviceId: ID,
      serviceName: 'Community nursing',
      version: 5,
      status: 'waiting',
      changeReason: 'Frailty pathway added',
      authorRole: 'Criteria owner',
      isAuthor: false,
      reviewMonths: 6,
      changedOn: '2026-10-30T09:00:00Z',
      criteria: { ageMin: 18, ageMax: null, accepts: [], excludes: [], districts: ['DT4'], reviewBy: '2027-04-30' },
      changes: [{ field: 'accepts', label: 'Accepts', before: [], after: ['frailty'], words: 'Accepts frailty' }],
    });
    const response = await GET(await callerRequest(`${url}`, 'lead'), ctx(ID));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      serviceName: 'Community nursing',
      taskId: 'CRIT-5',
      isAuthor: false,
      changes: ['Accepts frailty'],
      reason: 'Frailty pathway added',
      authorRole: 'Criteria owner',
    });
  });

  it('answers 404 when no change is waiting', async () => {
    answerBackend('get', `/criteria/${ID}/pending`, 404, { resourceType: 'OperationOutcome', issue: [] });
    expect((await GET(await callerRequest(url, 'lead'), ctx(ID))).status).toBe(404);
  });

  it('refuses the applicant, without calling the back end', async () => {
    expect((await GET(await callerRequest(url, 'reporter'), ctx(ID))).status).toBe(403);
    expect(seen).toHaveLength(0);
  });
});
