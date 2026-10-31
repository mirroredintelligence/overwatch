// @vitest-environment node
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { BACKEND_BASE } from '@/test/msw/handlers/board';
import { server } from '@/test/msw/server';
import { OPTIONS_PARAMETERS, OPTIONS_VIEW } from '@/test/fixtures/options';
import { OPTIONS as BACKEND_OPTIONS } from '@/test/fixtures/backend-shapes';
import { GET } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

const FILTER_URL = `${BACKEND_BASE}/HealthcareService/$filter-options`;
const NETWORKS_URL = 'http://backend.test/networks';
type Seen = { body: unknown; key: string | null; token: string | null };
const seen: Seen[] = [];

function session(role: Role): Session {
  return {
    role,
    tenantId: 'trust-a',
    host: 'app.test',
    services: [],
    sub: 'advisor-1',
    backendToken: 'token-for-advisor',
    expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
  };
}

async function get(role: Role | null, ref = '4821'): Promise<Response> {
  const cookies: Record<string, string> = {};
  if (role !== null) cookies[SESSION_COOKIE] = await sealSession(session(role));
  return GET(requestWithCookies(`https://app.test/api/bff/cases/${ref}/options`, cookies), {
    params: Promise.resolve({ ref }),
  });
}

beforeEach(() => {
  seen.length = 0;
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
  server.use(
    // By default the organisation is in no network: nothing more is read.
    http.get(NETWORKS_URL, () => HttpResponse.json({ networks: [] })),
    http.post(FILTER_URL, async ({ request }) => {
      seen.push({
        body: await request.clone().json(),
        key: request.headers.get('idempotency-key'),
        token: request.headers.get('authorization'),
      });
      return HttpResponse.json(OPTIONS_PARAMETERS);
    }),
  );
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('GET /api/bff/cases/[ref]/options (W13)', () => {
  it('calls $filter-options once for the case, with a key for this read and the session token', async () => {
    const response = await get('advisor');

    expect(response.status).toBe(200);
    expect(seen).toHaveLength(1);
    expect(seen[0].body).toEqual({
      resourceType: 'Parameters',
      parameter: [{ name: 'case', valueReference: { reference: 'ServiceRequest/4821' } }],
    });
    expect(seen[0].key).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
    expect(seen[0].token).toBe('Bearer token-for-advisor');
  });

  it('answers the options view in the back end order, with the not-suitable list', async () => {
    const body = (await (await get('advisor')).json()) as {
      shownAt: unknown;
      options: { serviceId: string; name: string; status: string; travelText: string | null }[];
      notSuitable: unknown;
    };

    expect(body.options.map((option) => option.serviceId)).toEqual(OPTIONS_VIEW.options.map((o) => o.serviceId));
    expect(body.options[0]).toMatchObject({ name: 'UCR West', status: 'accepting', travelText: 'about 35 to 50 min' });
    expect(body.notSuitable).toEqual(OPTIONS_VIEW.notSuitable);
    expect(typeof body.shownAt).toBe('string');
  });

  it('answers 403 for a reporter and calls nothing', async () => {
    expect((await get('reporter')).status).toBe(403);
    expect(seen).toHaveLength(0);
  });

  it('refuses a case reference that cannot be a case id, before any call', async () => {
    expect((await get('advisor', 'a%20b')).status).toBe(400);
    expect(seen).toHaveLength(0);
  });

  it('answers 502 when the back end sends something that is not Parameters', async () => {
    server.use(http.post(FILTER_URL, () => HttpResponse.json({ resourceType: 'Bundle' })));
    expect((await get('advisor')).status).toBe(502);
  });

  it('is never cached', async () => {
    expect((await get('advisor')).headers.get('cache-control')).toBe('private, no-store');
  });

  it('a tenant named in the address is refused with 400 and the back end is not called (DEC-130, TEN-044)', async () => {
    const cookies = { [SESSION_COOKIE]: await sealSession(session('advisor')) };
    const response = await GET(
      requestWithCookies('https://app.test/api/bff/cases/4821/options?tenantId=tenant-b', cookies),
      { params: Promise.resolve({ ref: '4821' }) },
    );

    expect(response.status).toBe(400);
    expect(seen).toHaveLength(0);
  });

  it('an organisation named in the address is ignored: the back end sees the session token and the case only (DEC-130)', async () => {
    const cookies = { [SESSION_COOKIE]: await sealSession(session('advisor')) };
    await GET(
      requestWithCookies('https://app.test/api/bff/cases/4821/options?organisation=other', cookies),
      { params: Promise.resolve({ ref: '4821' }) },
    );

    expect(seen).toHaveLength(1);
    expect(seen[0].token).toBe('Bearer token-for-advisor');
    expect(JSON.stringify(seen[0].body)).not.toMatch(/tenant|organisation|other/);
  });
});

// The other organisations' services, view only (KI-349, KI-181, KI-794, DEC-1176).
describe('GET /api/bff/cases/[ref]/options: the network services (B6)', () => {
  const networkOption = (BACKEND_OPTIONS.parameter as { name: string }[]).find(
    (item) => item.name === 'option' && JSON.stringify(item).includes('Neighbouring Trust'),
  );
  const ownParameters = {
    resourceType: 'Parameters',
    parameter: (BACKEND_OPTIONS.parameter as { name: string }[]).filter((item) => item !== networkOption),
  };
  const networkParameters = { resourceType: 'Parameters', parameter: [networkOption] };
  type Reply = { options: { serviceId: string; network: { organisation: string } | null; phone: string | null }[]; network: string };

  function answerWithNetworks(networks: { id: string }[]) {
    const calls: { body: unknown; key: string | null }[] = [];
    server.use(
      http.get(NETWORKS_URL, () => HttpResponse.json({ networks })),
      http.post(FILTER_URL, async ({ request }) => {
        const body = (await request.clone().json()) as { parameter: { name: string }[] };
        calls.push({ body, key: request.headers.get('idempotency-key') });
        return HttpResponse.json(body.parameter.some((part) => part.name === 'network') ? networkParameters : ownParameters);
      }),
    );
    return calls;
  }

  it('reads the networks of the session, then the network options of each, and puts them after the own services, each tagged with its organisation', async () => {
    const calls = answerWithNetworks([{ id: 'net-aa11' }]);

    const reply = (await (await get('advisor')).json()) as Reply;

    expect(calls).toHaveLength(2);
    expect(calls[1]?.body).toEqual({
      resourceType: 'Parameters',
      parameter: [
        { name: 'case', valueReference: { reference: 'ServiceRequest/4821' } },
        { name: 'network', valueString: 'net-aa11' },
      ],
    });
    expect(calls[0]?.key).not.toBe(calls[1]?.key);
    expect(reply.options.map((option) => option.serviceId)).toEqual(['svc-1', 'svc-2', 'svc-4', 'net-1']);
    expect(reply.options[3]).toMatchObject({ network: { organisation: 'Neighbouring Trust' }, phone: '01305 900300' });
    expect(reply.options.slice(0, 3).every((option) => option.network === null)).toBe(true);
    expect(reply.network).toBe('shown');
  });

  it('a row of the own answer that names an organisation is not taken as the viewer\'s own, and a network row with none is dropped', async () => {
    server.use(
      http.get(NETWORKS_URL, () => HttpResponse.json({ networks: [{ id: 'net-aa11' }] })),
      http.post(FILTER_URL, async ({ request }) => {
        const body = (await request.clone().json()) as { parameter: { name: string }[] };
        const isNetwork = body.parameter.some((part) => part.name === 'network');
        // A network answer whose row has no organisation must not be shown as the viewer's own service.
        return HttpResponse.json(isNetwork ? { resourceType: 'Parameters', parameter: [(ownParameters.parameter as unknown[])[0]] } : ownParameters);
      }),
    );

    const reply = (await (await get('advisor')).json()) as Reply;

    expect(reply.options.map((option) => option.serviceId)).toEqual(['svc-1', 'svc-2', 'svc-4']);
  });

  it('says none when the organisation is in no network, and reads no network options', async () => {
    const reply = (await (await get('advisor')).json()) as Reply;

    expect(seen).toHaveLength(1);
    expect(reply.network).toBe('none');
  });

  it('a failed network read leaves the own services and says the network could not be read', async () => {
    server.use(http.get(NETWORKS_URL, () => HttpResponse.json({}, { status: 500 })));

    const response = await get('advisor');
    const reply = (await response.json()) as Reply;

    expect(response.status).toBe(200);
    expect(reply.options.length).toBeGreaterThan(0);
    expect(reply.network).toBe('unavailable');
  });

  it('a refused network option read does the same', async () => {
    server.use(
      http.get(NETWORKS_URL, () => HttpResponse.json({ networks: [{ id: 'net-aa11' }] })),
      http.post(FILTER_URL, async ({ request }) => {
        const body = (await request.clone().json()) as { parameter: { name: string }[] };
        if (body.parameter.some((part) => part.name === 'network')) return HttpResponse.json({}, { status: 404 });
        return HttpResponse.json(ownParameters);
      }),
    );

    const reply = (await (await get('advisor')).json()) as Reply;

    expect(reply.options.every((option) => option.network === null)).toBe(true);
    expect(reply.network).toBe('unavailable');
  });

  it('reads at most three networks, and never an id that is not a network id', async () => {
    const calls = answerWithNetworks([{ id: 'net-aa11' }, { id: 'not a network' }, { id: 'net-bb22' }, { id: 'net-cc33' }, { id: 'net-dd44' }]);

    await get('advisor');

    const named = calls.map((call) => (call.body as { parameter: { name: string; valueString?: string }[] }).parameter.find((part) => part.name === 'network')?.valueString);
    expect(named).toEqual([undefined, 'net-aa11', 'net-bb22', 'net-cc33']);
  });

  it('with only=own it reads the own services and nothing else (the outcome form needs no network row)', async () => {
    const cookies = { [SESSION_COOKIE]: await sealSession(session('advisor')) };
    const calls = answerWithNetworks([{ id: 'net-aa11' }]);

    const response = await GET(
      requestWithCookies('https://app.test/api/bff/cases/4821/options?only=own', cookies),
      { params: Promise.resolve({ ref: '4821' }) },
    );
    const reply = (await response.json()) as Reply;

    expect(calls).toHaveLength(1);
    expect(reply.options.every((option) => option.network === null)).toBe(true);
    expect(reply.network).toBe('none');
  });

  it('puts no network id, tenant or network name in the answer beyond the organisation name', async () => {
    answerWithNetworks([{ id: 'net-aa11' }]);

    const text = JSON.stringify(await (await get('advisor')).json());

    expect(text).not.toContain('net-aa11');
    expect(text).not.toMatch(/tenant/i);
  });
});
