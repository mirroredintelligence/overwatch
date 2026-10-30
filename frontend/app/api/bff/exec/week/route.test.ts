// @vitest-environment node
import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Role, type Session } from '@/lib/auth/session';
import { requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { TOKEN_ORG_A } from '@/test/msw/handlers/board';
import { EXEC_BACKEND, execBackendHandlers, resetExecBackend } from '@/test/msw/handlers/exec';
import { server } from '@/test/msw/server';
import { GET } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});

const WEEK = `${EXEC_BACKEND}/HealthcareService/$week-summary`;
const askedWeekStart: string[] = [];

function figure(name: string, value: number | null, suppressed = false) {
  return { name, part: suppressed ? [{ name: 'suppressed', valueBoolean: true }] : [{ name: 'suppressed', valueBoolean: false }, { name: 'value', valueInteger: value }] };
}

async function get(role: Role, query: string) {
  const s: Session = { role, services: [], sub: 'user-1', backendToken: TOKEN_ORG_A, expiresAt: new Date(Date.now() + 3_600_000).toISOString() };
  return GET(requestWithCookies(`https://app.test/api/bff/exec/week${query}`, { [SESSION_COOKIE]: await sealSession(s) }));
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', EXEC_BACKEND);
  vi.stubEnv('NODE_ENV', 'production');
  resetExecBackend();
  server.use(...execBackendHandlers);
  askedWeekStart.length = 0;
  server.use(http.get(WEEK, (({ request }) => {
    askedWeekStart.push(new URL(request.url).searchParams.get('weekStart') ?? '');
    return HttpResponse.json({
      resourceType: 'Parameters',
      parameter: [
        { name: 'weekStart', valueDate: '2026-10-19' },
        figure('referrals', 640),
        figure('bestFitUnavailablePct', 18),
        figure('onTimePct', 92),
        figure('medianMinutesToConfirmed', 4),
        { name: 'updatesByChannel', part: [{ name: 'text', part: [{ name: 'suppressed', valueBoolean: false }, { name: 'value', valueInteger: 412 }] }] },
      ],
    });
  }) as HttpResponseResolver));
});

afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/exec/week', () => {
  it('answers the week ending on the given Sunday, with the minutes per call unset', async () => {
    const response = await get('exec', '?ending=2026-10-25');
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(expect.objectContaining({
      from: '2026-10-19',
      to: '2026-10-25',
      referrals: { value: 640, suppressed: false },
      updates: { value: 412, suppressed: false },
      minutesPerCall: null,
    }));
  });

  it('asks the back end for the Monday that starts that week', async () => {
    await get('exec', '?ending=2026-10-25');
    expect(askedWeekStart).toEqual(['2026-10-19']);
  });

  it('refuses an ending that is not a Sunday, without a back-end call', async () => {
    expect((await get('exec', '?ending=2026-10-23')).status).toBe(400);
  });

  it('refuses a malformed ending', async () => {
    expect((await get('exec', '?ending=yesterday')).status).toBe(400);
  });

  it('refuses a role that is not an executive or a shift lead', async () => {
    expect((await get('advisor', '?ending=2026-10-25')).status).toBe(403);
  });
});
