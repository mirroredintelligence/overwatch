// @vitest-environment node
import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Role } from '@/lib/auth/session';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { EXEC_BACKEND } from '@/test/msw/handlers/exec';
import { requestAs } from '@/test/requests';
import { server } from '@/test/msw/server';
import { TENANTS } from '@/test/tenants';
import { POST } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

const ROOT = EXEC_BACKEND.replace(/\/fhir$/, '');
const seen: { path: string; key: string | null; body: unknown }[] = [];

async function post(body: unknown, role: Role = 'exec') {
  return POST(await requestAs(TENANTS.A, role, {
    method: 'POST',
    path: '/api/bff/help/problems',
    csrf: true,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }));
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', EXEC_BACKEND);
  vi.stubEnv('NODE_ENV', 'production');
  seen.length = 0;
  // The back end's `POST /help/problems` (W7A, DEC-778) is at its root, not under /fhir.
  server.use(http.post(`${ROOT}/help/problems`, (async ({ request }) => {
    seen.push({ path: '/help/problems', key: request.headers.get('Idempotency-Key'), body: await request.json() });
    return HttpResponse.json({ id: 'PR-0042' }, { status: 201 });
  }) as HttpResponseResolver));
});

afterEach(() => vi.unstubAllEnvs());

describe('POST /api/bff/help/problems', () => {
  it('sends the report to the back end as its category and text, with an Idempotency-Key, and answers its id only', async () => {
    const response = await post({ kind: 'button-does-not-work', route: '/advisor/case/[ref]', text: 'The Send button does nothing.' });
    expect(response.status).toBe(201);
    expect(await response.json()).toEqual({ id: 'PR-0042' });
    expect(seen).toHaveLength(1);
    expect(seen[0]?.body).toEqual({ category: 'button-does-not-work', text: 'The Send button does nothing.' });
    expect(seen[0]?.key).toBeTruthy();
  });

  it('sends no text when none is given, and never the page route, which the back end does not hold', async () => {
    await post({ kind: 'screen-slow', route: '/help' });
    expect(seen[0]?.body).toEqual({ category: 'screen-slow' });
    expect(JSON.stringify(seen[0]?.body)).not.toContain('/help');
  });

  it('refuses a kind the back end does not hold, with 400 and no back-end call', async () => {
    expect((await post({ kind: 'button-not-working', route: '/help' })).status).toBe(400);
    expect(seen).toHaveLength(0);
  });

  it('refuses a route that is not a page path, with 400', async () => {
    expect((await post({ kind: 'screen-slow', route: 'https://elsewhere.example/x' })).status).toBe(400);
    expect(seen).toHaveLength(0);
  });

  it('refuses a text over 280 characters, with 400 and no call', async () => {
    expect((await post({ kind: 'screen-slow', route: '/help', text: 'x'.repeat(281) })).status).toBe(400);
    expect(seen).toHaveLength(0);
  });

  it('says the service is unavailable when the back end fails, and never that the report was sent', async () => {
    server.use(http.post(`${ROOT}/help/problems`, () => HttpResponse.json({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'exception', diagnostics: 'x' }] }, { status: 503 })));
    const response = await post({ kind: 'screen-slow', route: '/help' });
    expect(response.status).toBe(503);
  });

  it('refuses a person with no session', async () => {
    const response = await POST(new Request('https://tenant-a.example.test/api/bff/help/problems', { method: 'POST', body: '{}' }));
    expect(response.status).toBe(401);
  });
});
