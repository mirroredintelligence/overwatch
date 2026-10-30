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

// The address lookup for a fixed site (W24). A postcode is normalised here, then looked up by the
// back end, which answers at most twenty addresses: each is an id and a label, nothing else.

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  resetSeen();
});

describe('GET /api/bff/addresses', () => {
  it('looks up the normalised postcode with the bearer token and answers the addresses as id and label', async () => {
    answerBackend('get', '/addresses', 200, {
      addresses: [{ id: '100090001', label: '1 High Street, Dorchester', uprn: '100090001', x: 1 }],
    });
    const response = await GET(await callerRequest('https://tenant-a.example.test/api/bff/addresses?postcode=dt48xx'));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual([{ id: '100090001', label: '1 High Street, Dorchester' }]);
    expect(seen[0]).toMatchObject({ path: '/addresses', auth: 'Bearer backend-token-sample-value' });
  });

  it('refuses a postcode that is not one, without calling the back end', async () => {
    const response = await GET(await callerRequest('https://tenant-a.example.test/api/bff/addresses?postcode=notapostcode'));
    expect(response.status).toBe(400);
    expect(seen).toHaveLength(0);
  });

  it('answers 503 when the back end cannot look up addresses', async () => {
    breakBackend('get', '/addresses');
    const response = await GET(await callerRequest('https://tenant-a.example.test/api/bff/addresses?postcode=DT4%208XX'));
    expect(response.status).toBe(503);
  });
});
