// @vitest-environment node
import { http, HttpResponse, type HttpResponseResolver } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SESSION_COOKIE, sealSession, type Session } from '@/lib/auth/session';
import { CSRF_COOKIE, CSRF_HEADER } from '@/lib/auth/csrf';
import { readRegistration } from '@/lib/register/backend';
import { BACKEND_ROOT } from '@/test/fixtures/links';
import { cookiesMock, requestWithCookies, TEST_SESSION_SECRET } from '@/test/cookies';
import { server } from '@/test/msw/server';
import { PUT } from './route';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock };
});
vi.mock('@/lib/register/backend', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/register/backend')>()),
  readRegistration: vi.fn(),
}));

// The organisation step save (W54). The browser sends only its answers; the invitation's values are
// read from the back end here, and the back end's own checks answer the save.

const ID = 'REG-SAMPLE-1';
const CSRF = 'csrf-sample-token';
const read = vi.mocked(readRegistration);
const url = (step = 'organisation') => `https://tenant-a.example.test/api/bff/registrations/${ID}/steps/${step}`;
const ctx = (step = 'organisation', id = ID) => ({ params: Promise.resolve({ id, step }) });

let upstream: { path: string; method: string; body: unknown; auth: string | null; idem: string | null } | null = null;

async function sessionFor(role: Session['role']): Promise<string> {
  return sealSession({
    role,
    services: [],
    sub: 'person-sample-1',
    backendToken: 'backend-token-sample-value',
    expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
  });
}

function answerWith(status: number, body: unknown) {
  server.use(
    http.put(`${BACKEND_ROOT}/fhir/Task/${ID}/$draft`, (async ({ request }) => {
      upstream = {
        path: new URL(request.url).pathname,
        method: request.method,
        body: await request.json(),
        auth: request.headers.get('authorization'),
        idem: request.headers.get('idempotency-key'),
      };
      return HttpResponse.json(body as Record<string, unknown>, { status });
    }) as HttpResponseResolver),
  );
}

async function save(body: unknown, role: Session['role'] = 'reporter', csrf: string | null = CSRF, step = 'organisation') {
  const cookies = { [SESSION_COOKIE]: await sessionFor(role), [CSRF_COOKIE]: CSRF };
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (csrf !== null) headers[CSRF_HEADER] = csrf;
  return PUT(
    requestWithCookies(url(step), cookies, { method: 'PUT', headers, body: typeof body === 'string' ? body : JSON.stringify(body) }),
    ctx(step),
  );
}

beforeEach(() => {
  vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
  vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
  cookiesMock.mockClear();
  upstream = null;
  read.mockReset();
  read.mockResolvedValue({
    id: ID,
    status: 'draft',
    invitation: { serviceName: 'UCR West', organisationName: 'Sample Community Trust', odsCode: 'RSA01' },
    steps: {},
  });
  answerWith(200, { resourceType: 'Task', id: ID, businessStatus: { coding: [{ system: 'x', code: 'draft' }] } });
});

describe('PUT /api/bff/registrations/[id]/steps/organisation', () => {
  it('saves the answers with the invitation’s values, as the back end’s step, with the bearer token and an idempotency key', async () => {
    const response = await save({ orgType: 'nhs-trust', contactName: 'Sample Person', contactRole: 'Lead', contact: 'contact@example.test' });
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ status: 'draft' });
    expect(upstream).toMatchObject({
      path: `/fhir/Task/${ID}/$draft`,
      method: 'PUT',
      auth: 'Bearer backend-token-sample-value',
    });
    expect(upstream?.idem).toMatch(/^[0-9a-f-]{36}$/);
    expect(upstream?.body).toEqual({
      step: 'organisation',
      values: {
        name: 'Sample Community Trust',
        odsCode: 'RSA01',
        orgType: 'nhs-trust',
        contactName: 'Sample Person',
        contactEmail: 'contact@example.test',
      },
    });
  });

  it('sends nothing for the role line, which the back end does not take yet', async () => {
    await save({ contactName: 'Sample Person', contactRole: 'Lead' });
    expect(upstream?.body).not.toHaveProperty('values.contactRole');
    expect((upstream?.body as { values: object }).values).not.toHaveProperty('contactRole');
  });

  it('answers the back end’s refusals as 422 with the errors on the page’s fields, and no value', async () => {
    answerWith(400, {
      resourceType: 'OperationOutcome',
      issue: [
        { severity: 'error', code: 'invalid', diagnostics: 'Enter a contact email or phone number', expression: ['contactEmail'] },
        { severity: 'error', code: 'invalid', diagnostics: 'Choose an organisation type', expression: ['orgType'] },
      ],
    });
    const response = await save({ contactName: 'Sample Person', contact: 'contact@example.test' });
    expect(response.status).toBe(422);
    const body = (await response.json()) as { errors: { field: string; message: string }[] };
    expect(body.errors).toEqual([
      { field: 'contact', message: 'Enter a contact email or phone number' },
      { field: 'orgType', message: 'Choose an organisation type' },
    ]);
    expect(JSON.stringify(body)).not.toContain('Sample Person');
  });

  it('refuses a save with no CSRF header (403) and writes nothing upstream', async () => {
    const response = await save({ contactName: 'Sample Person' }, 'reporter', null);
    expect(response.status).toBe(403);
    expect(upstream).toBeNull();
  });

  it('refuses a body that names a tenant, a locked field or any other field, without calling the back end', async () => {
    for (const extra of [{ tenantId: 'tenant-b' }, { name: 'Other Trust' }, { odsCode: 'ZZZ99' }, { orgRole: 'x' }]) {
      const response = await save({ contactName: 'Sample Person', ...extra });
      expect(response.status).toBe(400);
    }
    expect(upstream).toBeNull();
  });

  it('answers 404 for a step the registration does not have, and 403 for another role', async () => {
    expect((await save({}, 'reporter', CSRF, 'payments')).status).toBe(404);
    expect((await save({ contactName: 'x' }, 'advisor')).status).toBe(403);
    expect(upstream).toBeNull();
  });

  it('answers 503 not-built while the back end has no registration read, and saves nothing', async () => {
    const { FhirError } = await import('@/lib/fhir/client');
    read.mockRejectedValueOnce(new FhirError(503, { resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'not-built', diagnostics: 'x' }] }));
    const response = await save({ contactName: 'Sample Person' });
    expect(response.status).toBe(503);
    expect(await response.json()).toMatchObject({ code: 'not-built' });
    expect(upstream).toBeNull();
  });
});
