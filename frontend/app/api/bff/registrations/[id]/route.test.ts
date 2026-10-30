// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BACKEND_ROOT } from '@/test/fixtures/links';
import { answerBackend, breakBackend, resetSeen, seen } from '@/test/applicant/backend';
import { callerRequest } from '@/test/applicant/session';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { withApplicantHandlers } from '@/test/msw/applicant';
import { GET } from './route';

// The applicant's record and the lead's overview share this path; each role has its own describe below.

withApplicantHandlers();

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

// The applicant's own registration (W54 to W26): the back end's record, mapped to what the steps
// show. The record holds no invitation, so the view names the service and the saved answers only.
// Another person's registration and an unknown one are the same 404.

const ID = 'REG-SAMPLE-1';
const url = `https://tenant-a.example.test/api/bff/registrations/${ID}`;
const ctx = (id: string) => ({ params: Promise.resolve({ id }) });

const RECORD = {
  registrationId: ID,
  status: 'draft',
  serviceId: 'SVC-SAMPLE-1',
  serviceName: 'Community nursing',
  submittedAt: null,
  lastModified: '2026-10-30T09:00:00Z',
  invitationExpiresAt: '2026-11-01T18:00:00Z',
  note: '',
  noteFrom: null,
  steps: {
    organisation: { state: 'complete', values: { name: 'Sample Community Trust', odsCode: 'SAM01', orgType: 'nhs-trust', contactName: 'Sam Sample', contactEmail: 'sam@example.test', contactPhone: '07700900456' }, problems: [] },
    location: { state: 'not-started', values: {}, problems: [] },
    service: { state: 'not-started', values: {}, problems: [] },
    reporting: { state: 'not-started', values: {}, problems: [] },
    api: { state: 'not-started', values: {}, problems: [] },
  },
};

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  resetSeen();
});

describe('GET /api/bff/registrations/[id] (the applicant’s record)', () => {
  it('reads the record with the reporter’s bearer token and answers the service and the saved steps, with no invitation', async () => {
    answerBackend('get', `/registrations/${ID}/record`, 200, RECORD);
    const response = await GET(await callerRequest(url), ctx(ID));
    expect(response.status).toBe(200);
    expect(response.headers.get('cache-control')).toBe('private, no-store');
    const body = (await response.json()) as Record<string, unknown>;
    expect(body).toMatchObject({ id: ID, status: 'draft', serviceName: 'Community nursing' });
    expect(body).not.toHaveProperty('invitation');
    expect(body.steps).toMatchObject({
      organisation: { name: 'Sample Community Trust', odsCode: 'SAM01', orgType: 'nhs-trust', contactName: 'Sam Sample', contactEmail: 'sam@example.test', contactPhoneEnding: '456' },
    });
    expect(JSON.stringify(body)).not.toContain('07700900456');
    expect(seen).toHaveLength(1);
    expect(seen[0]).toMatchObject({ path: `/registrations/${ID}/record`, auth: 'Bearer backend-token-sample-value' });
  });

  it('answers the same 404 for an unknown registration and for another person’s', async () => {
    answerBackend('get', `/registrations/${ID}/record`, 404, { resourceType: 'OperationOutcome', issue: [] });
    const response = await GET(await callerRequest(url), ctx(ID));
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ code: 'not-found', message: 'We could not find that.' });
  });

  it('answers 503 when the back end answers a record the screens cannot use', async () => {
    answerBackend('get', `/registrations/${ID}/record`, 200, { registrationId: ID, status: 'nonsense' });
    const response = await GET(await callerRequest(url), ctx(ID));
    expect(response.status).toBe(503);
  });

  it('answers 503 with no detail when the back end cannot be reached', async () => {
    breakBackend('get', `/registrations/${ID}/record`);
    const response = await GET(await callerRequest(url), ctx(ID));
    expect(response.status).toBe(503);
    expect(await response.text()).not.toMatch(/fetch|ECONN/i);
  });

  it('refuses a caller with no session, and an advisor, without calling the back end', async () => {
    const noSession = new Request(url);
    expect((await GET(noSession, ctx(ID))).status).toBe(401);
    expect((await GET(await callerRequest(url, 'advisor'), ctx(ID))).status).toBe(403);
    expect(seen).toHaveLength(0);
  });
});

describe('GET /api/bff/registrations/[id] (the lead’s review overview)', () => {
  it('reads the overview with the lead’s token and answers the checks, the manual checks and the words of the call-back', async () => {
    answerBackend('get', `/registrations/${ID}/overview`, 200, {
      registrationId: ID,
      status: 'in-review',
      serviceId: 'SVC-SAMPLE-1',
      serviceName: 'Community nursing',
      category: 'urgent-community-response',
      checks: [{ name: 'ods', passed: true, ok: true, message: 'The ODS code is on the register', explainedNote: null }],
      automaticOk: true,
      callbackConfirmed: false,
      scope: null,
      criteriaApproved: false,
      missing: ['The call-back is not confirmed'],
      registeredBy: { role: 'Duty manager', contactName: 'Sam Sample', organisationName: 'Sample Community Trust' },
      applicantNumbers: [{ label: 'Reporting', ending: '456' }],
      callBack: { numberToCall: null, directoryName: 'the area directory', pathwayName: 'Urgent community response pathway' },
    });
    const response = await GET(await callerRequest(url, 'lead'), ctx(ID));
    expect(response.status).toBe(200);
    const body = (await response.json()) as Record<string, unknown>;
    expect(body).toMatchObject({
      id: ID,
      serviceName: 'Community nursing',
      registeredBy: { name: 'Sam Sample', role: 'Duty manager' },
      manualChecks: { callback: 'not-done', scope: 'not-done', criteria: 'not-done' },
      pathwayName: 'Urgent community response pathway',
    });
    expect(JSON.stringify(body)).not.toContain('Sample Community Trust');
    expect(JSON.stringify(body)).not.toContain('456');
  });

  it('answers 404 for a registration the lead cannot see', async () => {
    answerBackend('get', `/registrations/${ID}/overview`, 404, { resourceType: 'OperationOutcome', issue: [] });
    expect((await GET(await callerRequest(url, 'lead'), ctx(ID))).status).toBe(404);
  });
});
