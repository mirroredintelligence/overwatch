// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { GET } from './route';

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

const ROOT = BACKEND_BASE.replace(/\/fhir$/, '');
const URL_ = 'https://app.test/api/bff/lead/reporters?service=s-ucr-east';

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/lead/reporters', () => {
  it('answers 403 to an advisor', async () => {
    expect((await GET(await leadRequest(URL_, 'advisor'))).status).toBe(403);
  });

  it('gives each post with its last four digits, and never the role id or a whole number', async () => {
    let service: string | null = null;
    server.use(
      http.get(`${ROOT}/lead/reporters`, ({ request }) => {
        service = new URL(request.url).searchParams.get('service');
        return HttpResponse.json({
          reporters: [
            { serviceId: 's-ucr-east', serviceName: 'UCR East', roleId: 'role-ucr-east', role: 'Duty manager', channel: 'text', numberEnding: '4821', coveredUntil: '2026-10-30T20:00:00Z' },
          ],
        });
      }),
    );
    const response = await GET(await leadRequest(URL_, 'lead'));
    expect(response.status).toBe(200);
    expect(service).toBe('s-ucr-east');
    const text = await response.text();
    expect(JSON.parse(text)).toEqual({
      reporters: [
        { serviceId: 's-ucr-east', serviceName: 'UCR East', role: 'Duty manager', channel: 'text', numberEnding: '4821', coveredUntil: '2026-10-30T20:00:00Z' },
      ],
    });
    expect(text).not.toContain('role-ucr-east');
  });
});
