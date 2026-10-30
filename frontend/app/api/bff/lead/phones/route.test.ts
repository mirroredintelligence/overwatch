// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { GET } from './route';

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/lead/phones', () => {
  it('answers 403 to an advisor', async () => {
    expect((await GET(await leadRequest('https://app.test/api/bff/lead/phones', 'advisor'))).status).toBe(403);
  });

  it('answers 501 for a lead until the back end lists the phones, and never an empty list', async () => {
    const response = await GET(await leadRequest('https://app.test/api/bff/lead/phones', 'lead'));
    expect(response.status).toBe(501);
    expect(await response.json()).not.toHaveProperty('phones');
  });
});
