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
    expect(response.headers.get('cache-control')).toBe('no-store');
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
