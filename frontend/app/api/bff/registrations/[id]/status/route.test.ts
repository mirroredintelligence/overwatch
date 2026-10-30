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

// The applicant's status page (W27): the back end's status answer, reduced to what the page shows.
// The note is a text and its sender a role; the phone is its last three digits only.

const ID = 'REG-SAMPLE-1';
const url = `https://tenant-a.example.test/api/bff/registrations/${ID}/status`;
const ctx = (id: string) => ({ params: Promise.resolve({ id }) });

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  resetSeen();
});

describe('GET /api/bff/registrations/[id]/status', () => {
  it('answers the status, the note as a list with its sender, and the details, and nothing else', async () => {
    answerBackend('get', `/registrations/${ID}/status`, 200, {
      registrationId: ID,
      status: 'needs-changes',
      serviceName: 'Community nursing',
      submittedAt: '2026-10-29T09:00:00Z',
      note: 'Check the phone number.',
      noteFrom: 'lead',
      reason: null,
      firstPromptAt: null,
      reviewRequestedAt: null,
      testSentAt: null,
      details: { spoaPhone: '01305 000111', criteriaOwner: null, reportingPhoneEnding: '456' },
      tenantId: 'tenant-a',
    });
    const response = await GET(await callerRequest(url), ctx(ID));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      status: 'needs-changes',
      serviceName: 'Community nursing',
      submittedAt: '2026-10-29T09:00:00Z',
      notes: ['Check the phone number.'],
      noteFrom: { role: 'lead' },
      details: { spoaPhone: '01305 000111', reportingPhoneEnding: '456' },
    });
    expect(seen[0]).toMatchObject({ path: `/registrations/${ID}/status`, auth: 'Bearer backend-token-sample-value' });
  });

  it('answers 404 for a registration the applicant does not hold', async () => {
    answerBackend('get', `/registrations/${ID}/status`, 404, { resourceType: 'OperationOutcome', issue: [] });
    const response = await GET(await callerRequest(url), ctx(ID));
    expect(response.status).toBe(404);
  });
});
