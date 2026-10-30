// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { leadRequest } from '@/test/lead-session';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { BACKEND_ROOT } from '@/test/msw/handlers/lead';
import { server } from '@/test/msw/server';
import { GET } from './route';

vi.mock('next/headers', async () => ({ cookies: (await import('@/test/cookies')).cookiesMock }));

const URL_ = 'https://app.test/api/bff/lead/flags?state=to-check';

const BUNDLE = {
  resourceType: 'Bundle',
  type: 'searchset',
  total: 1,
  entry: [
    {
      resource: {
        resourceType: 'Flag',
        id: 'flag-1',
        status: 'active',
        code: { coding: [{ code: 'out-of-range-twice' }] },
        subject: { reference: 'HealthcareService/s-ucr-east', display: 'UCR East' },
      },
    },
  ],
};

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
});

afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/lead/flags', () => {
  it('answers the open flags with their counts, from the back end list of open flags', async () => {
    let asked: string | null = null;
    server.use(
      http.get(`${BACKEND_ROOT}/admin/report-flags`, ({ request }) => {
        asked = new URL(request.url).searchParams.get('status');
        return HttpResponse.json(BUNDLE);
      }),
    );
    const response = await GET(await leadRequest(URL_, 'lead'));
    expect(response.status).toBe(200);
    expect(asked).toBe('open');
    expect(await response.json()).toEqual({
      counts: { toCheck: 1, checked: null },
      items: [
        {
          id: 'flag-1',
          serviceId: 's-ucr-east',
          serviceName: 'UCR East',
          reason: 'out-of-range-twice',
          summary: 'The figure was out of its usual range twice.',
        },
      ],
    });
  });

  it('answers the checked flags from the back end list of closed flags, with their count', async () => {
    let asked: string | null = null;
    server.use(
      http.get(`${BACKEND_ROOT}/admin/report-flags`, ({ request }) => {
        asked = new URL(request.url).searchParams.get('status');
        return HttpResponse.json({ ...BUNDLE, total: 1, entry: [{ resource: { ...BUNDLE.entry[0].resource, status: 'inactive', outcome: 'accepted' } }] });
      }),
    );
    const response = await GET(await leadRequest('https://app.test/api/bff/lead/flags?state=checked', 'lead'));
    expect(response.status).toBe(200);
    expect(asked).toBe('closed');
    const body = (await response.json()) as { counts: unknown; items: { id: string }[] };
    expect(body.counts).toEqual({ toCheck: null, checked: 1 });
    expect(body.items.map((item) => item.id)).toEqual(['flag-1']);
  });

  it('answers 503 when the checked list cannot be read, and never an empty list', async () => {
    server.use(http.get(`${BACKEND_ROOT}/admin/report-flags`, () => HttpResponse.json({}, { status: 503 })));
    const response = await GET(await leadRequest('https://app.test/api/bff/lead/flags?state=checked', 'lead'));
    expect(response.status).toBe(503);
  });

  it('answers 400 for a state it does not know', async () => {
    expect((await GET(await leadRequest('https://app.test/api/bff/lead/flags?state=all', 'lead'))).status).toBe(400);
  });

  it('answers 403 to an advisor', async () => {
    expect((await GET(await leadRequest(URL_, 'advisor'))).status).toBe(403);
  });
});
