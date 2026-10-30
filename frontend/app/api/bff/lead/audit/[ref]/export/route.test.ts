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

const ctx = (ref: string) => ({ params: Promise.resolve({ ref }) });

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', BACKEND_BASE);
  vi.stubEnv('NODE_ENV', 'production');
  server.use(
    http.get(`${BACKEND_ROOT}/admin/audit/4821`, () =>
      HttpResponse.json({
        reference: '4821',
        shown_at: '2026-10-23T13:13:20Z',
        chain_ok: true,
        rows: [{ service_name: 'UCR West, Reablement', status: 'Accepting', value_text: '4', data_age_text: '9 min old', criteria_version: 3 }],
        timeline: [{ at: '2026-10-23T13:12:00Z', label: 'Case 4821 opened' }],
      }),
    ),
  );
});

afterEach(() => vi.unstubAllEnvs());

describe('GET /api/bff/lead/audit/[ref]/export', () => {
  it('answers a CSV attachment, with the same fields as the screen and the service name quoted', async () => {
    const response = await GET(await leadRequest('https://app.test/api/bff/lead/audit/4821/export', 'lead'), ctx('4821'));
    expect(response.status).toBe(200);
    expect(response.headers.get('content-type')).toBe('text/csv; charset=utf-8');
    expect(response.headers.get('content-disposition')).toBe('attachment; filename="audit-4821.csv"');
    expect(response.headers.get('cache-control')).toBe('private, no-store');
    const text = await response.text();
    expect(text.split('\r\n')[0]).toBe('Type,Time,Service,Status,Figure,Data age,Criteria version,Event');
    expect(text).toContain('"UCR West, Reablement"');
  });

  it('answers 404 for a malformed reference, with the same words as an unknown one', async () => {
    const response = await GET(await leadRequest('https://app.test/api/bff/lead/audit/x/export', 'lead'), ctx('a b'));
    expect(response.status).toBe(404);
  });

  it('answers 403 to an advisor', async () => {
    expect((await GET(await leadRequest('https://app.test/api/bff/lead/audit/4821/export', 'advisor'), ctx('4821'))).status).toBe(403);
  });
});
