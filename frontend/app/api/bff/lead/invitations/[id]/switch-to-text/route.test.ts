// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { POST } from './route';

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

const URL_ = 'https://app.test/api/bff/lead/invitations/inv-1/switch-to-text';
const ctx = { params: Promise.resolve({ id: 'inv-1' }) };

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/lead/invitations/[id]/switch-to-text', () => {
  it('answers 403 to an advisor and 501 for a lead until the back end can switch the channel', async () => {
    expect((await POST(await leadRequest(URL_, 'advisor', { method: 'POST', csrf: true, key: 'k-0001' }), ctx)).status).toBe(403);
    expect((await POST(await leadRequest(URL_, 'lead', { method: 'POST', csrf: true, key: 'k-0001' }), ctx)).status).toBe(501);
  });
});
