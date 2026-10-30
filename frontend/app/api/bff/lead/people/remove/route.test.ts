// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { POST } from './route';

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

const URL_ = 'https://app.test/api/bff/lead/people/remove';
const KEY = 'remove-key-0001';

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/lead/people/remove', () => {
  it('answers 403 to an advisor', async () => {
    expect((await POST(await leadRequest(URL_, 'advisor', { method: 'POST', csrf: true, key: KEY, body: { person: 'role-42', reason: 'lost-phone' } }))).status).toBe(403);
  });

  it('answers 400 for a reason it does not know, and for a person that is not a role id', async () => {
    expect((await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY, body: { person: 'role-42', reason: 'bored' } }))).status).toBe(400);
    expect((await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY, body: { person: '07700 900456', reason: 'lost-phone' } }))).status).toBe(400);
  });

  it('answers 501 for a valid removal until the people list gives a role id to remove, and changes nothing', async () => {
    const response = await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: KEY, body: { person: 'role-42', reason: 'lost-phone' } }));
    expect(response.status).toBe(501);
    expect(await response.text()).not.toContain('07700');
  });
});
