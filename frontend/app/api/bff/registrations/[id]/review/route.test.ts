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

// The review (W26): one row per answered step, complete or needing attention, with the words the back
// end gives. The back end has no review route for the applicant: the rows come from the record's steps.

const ID = 'REG-SAMPLE-1';
const url = `https://tenant-a.example.test/api/bff/registrations/${ID}/review`;
const ctx = (id: string) => ({ params: Promise.resolve({ id }) });

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  resetSeen();
});

describe('GET /api/bff/registrations/[id]/review', () => {
  it('answers one row per answered step, from the record, and nothing else', async () => {
    answerBackend('get', `/registrations/${ID}/record`, 200, {
      registrationId: ID,
      status: 'draft',
      serviceId: 'SVC-SAMPLE-1',
      serviceName: 'Community nursing',
      submittedAt: null,
      lastModified: '2026-10-30T09:00:00Z',
      invitationExpiresAt: null,
      note: '',
      noteFrom: null,
      steps: {
        organisation: { state: 'complete', values: { name: 'Sample Community Trust' }, problems: [] },
        location: { state: 'not-started', values: {}, problems: [] },
        service: { state: 'needs-attention', values: {}, problems: [{ field: 'spoaPhone', message: 'Enter a phone number' }] },
        reporting: { state: 'complete', values: {}, problems: [] },
        api: { state: 'not-started', values: {}, problems: [] },
      },
    });
    const response = await GET(await callerRequest(url), ctx(ID));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      sections: [
        { key: 'organisation', status: 'complete', summary: '' },
        { key: 'service', status: 'needs-attention', summary: 'Enter a phone number' },
        { key: 'reporting', status: 'complete', summary: '' },
      ],
    });
    expect(seen).toHaveLength(1);
  });
});
