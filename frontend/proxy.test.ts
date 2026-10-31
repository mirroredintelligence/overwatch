// @vitest-environment node
import { NextRequest } from 'next/server';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { canAccess } from '@/lib/auth/access';
import { ROLES, sealSession, SESSION_COOKIE, type Role, type Session } from '@/lib/auth/session';
import { TEST_SESSION_SECRET } from '@/test/cookies';
import { OPERATOR_COOKIE, sealOperatorSession, type OperatorRole } from '@/lib/operator/session';
import { OPERATOR_HOST, operatorSessionFor } from '@/test/operator';
import { config, proxy } from './proxy';

// The role guard (W09). The session is read from the sealed cookie and from
// nothing else: not the query string, not a header.

const BASE = 'https://capacity.example.test';

beforeEach(() => vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET));
afterEach(() => vi.unstubAllEnvs());

function sessionFor(role: Role, overrides: Partial<Session> = {}): Session {
  return {
    role,
    tenantId: 'trust-a',
    host: new URL(BASE).host,
    services: [],
    sub: 'aaaaaaaa-0000-4000-8000-000000000001',
    backendToken: 'backend-token-sample-value',
    expiresAt: new Date(Date.now() + 3_600_000).toISOString(),
    ...overrides,
  };
}

async function request(path: string, role?: Role, init: { cookie?: string; headers?: Record<string, string> } = {}) {
  const headers = new Headers(init.headers);
  const cookie = init.cookie ?? (role ? `${SESSION_COOKIE}=${await sealSession(sessionFor(role))}` : undefined);
  if (cookie) headers.set('cookie', cookie);
  return new NextRequest(`${BASE}${path}`, { headers });
}

function redirectedTo(response: Response | undefined): string | null {
  if (!response) return null;
  const location = response.headers.get('location');
  if (!location || response.status < 300 || response.status > 399) return null;
  const url = new URL(location);
  return url.pathname + url.search;
}

function rewrittenTo(response: Response | undefined): string | null {
  const target = response?.headers.get('x-middleware-rewrite');
  if (!target) return null;
  const url = new URL(target);
  return url.pathname + url.search;
}

function passes(response: Response | undefined): boolean {
  return response?.headers.get('x-middleware-next') === '1';
}

describe('no session', () => {
  it('sends /lead to /sign-in?next=%2Flead', async () => {
    const response = await proxy(await request('/lead'));
    expect(redirectedTo(response)).toBe('/sign-in?next=%2Flead');
  });

  it('keeps the query string in next', async () => {
    const response = await proxy(await request('/lead?tab=late'));
    expect(redirectedTo(response)).toBe('/sign-in?next=%2Flead%3Ftab%3Dlate');
  });

  it.each(['/advisor', '/advisor/case/4821', '/clinical', '/owner/criteria', '/planning', '/console'])(
    'sends %s to sign-in',
    async (path) => {
      const response = await proxy(await request(path));
      expect(redirectedTo(response)).toBe(`/sign-in?next=${encodeURIComponent(path)}`);
    },
  );

  it('does not let the browser cache the answer', async () => {
    const response = await proxy(await request('/lead'));
    expect(response?.headers.get('cache-control')).toBe('no-store');
  });

  it.each(['/Lead', '/%6Cead', '//lead', '/lead/', '/x%2F..%2Flead'])('also guards the path written as %s', async (path) => {
    const response = await proxy(await request(path));
    expect(redirectedTo(response)).toMatch(/^\/sign-in/);
  });

  it('leaves unguarded paths alone, and does not need the session secret for them', async () => {
    vi.stubEnv('SESSION_SECRET', '');
    for (const path of ['/', '/screen', '/screen/pair', '/sign-in', '/forbidden', '/api/bff/board', '/case/4821']) {
      const response = await proxy(await request(path));
      expect(response === undefined || passes(response)).toBe(true);
      expect(redirectedTo(response)).toBeNull();
    }
  });
});

describe('the Twilio webhooks (DEC-1302): public, before any session', () => {
  const PATHS = ['/webhooks/sms/twilio', '/webhooks/sms/twilio/status'];

  async function post(path: string, init: { cookie?: string; headers?: Record<string, string> } = {}) {
    const headers = new Headers({ 'content-type': 'application/x-www-form-urlencoded', 'x-twilio-signature': 'SampleSignature=', ...init.headers });
    if (init.cookie) headers.set('cookie', init.cookie);
    return new NextRequest(`${BASE}${path}`, { method: 'POST', headers, body: 'From=%2B447700900123' });
  }

  it.each(PATHS)('lets POST %s through with no session: no redirect to sign-in, no rewrite to the forbidden page', async (path) => {
    const response = await proxy(await post(path));
    expect(passes(response)).toBe(true);
    expect(redirectedTo(response)).toBeNull();
    expect(rewrittenTo(response)).toBeNull();
    expect(response.status).toBe(200);
  });

  it.each(PATHS)('lets POST %s through when the browser holds a bad, expired or foreign session, or an operator’s', async (path) => {
    for (const cookie of [`${SESSION_COOKIE}=garbage`, `${OPERATOR_COOKIE}=garbage`, `${SESSION_COOKIE}=`]) {
      const response = await proxy(await post(path, { cookie }));
      expect(passes(response), cookie).toBe(true);
      expect(redirectedTo(response), cookie).toBeNull();
    }
  });

  it('does not need the session secret to let them through', async () => {
    vi.stubEnv('SESSION_SECRET', '');
    for (const path of PATHS) expect(passes(await proxy(await post(path)))).toBe(true);
  });

  it('lets every path under /webhooks through too, for its own route to answer 404: the proxy guards no path of it', async () => {
    for (const path of ['/webhooks', '/webhooks/', '/webhooks/sms/other', '/webhooks/sms/twilio/extra', '/webhooks/x/y/z']) {
      const response = await proxy(await post(path));
      expect(passes(response), path).toBe(true);
      expect(redirectedTo(response), path).toBeNull();
    }
  });

  it('is matched by the proxy’s matcher, so the policy and security headers are on the answer too', () => {
    const patterns = config.matcher.map((m) => new RegExp(`^${m}$`));
    for (const path of ['/webhooks/sms/twilio', '/webhooks/sms/twilio/status']) expect(patterns.some((p) => p.test(path)), path).toBe(true);
  });
});

describe('a session that is not good', () => {
  it('sends an expired session to sign-in', async () => {
    const past = new Date(Date.now() - 9 * 3_600_000);
    const sealed = await sealSession(sessionFor('lead', { expiresAt: new Date(past.getTime() + 8 * 3_600_000).toISOString() }), past);
    const response = await proxy(await request('/lead', undefined, { cookie: `${SESSION_COOKIE}=${sealed}` }));
    expect(redirectedTo(response)).toBe('/sign-in?next=%2Flead');
  });

  it('sends a cookie that is not a session, or was sealed with another key, to sign-in', async () => {
    const other = Buffer.alloc(32, 1).toString('base64');
    vi.stubEnv('SESSION_SECRET', other);
    const foreign = await sealSession(sessionFor('lead'));
    vi.stubEnv('SESSION_SECRET', TEST_SESSION_SECRET);
    for (const value of ['garbage', foreign, '']) {
      const response = await proxy(await request('/lead', undefined, { cookie: `${SESSION_COOKIE}=${value}` }));
      expect(redirectedTo(response)).toBe('/sign-in?next=%2Flead');
    }
  });

  it('fails closed when the session secret is not set: an error, never a pass', async () => {
    vi.stubEnv('SESSION_SECRET', '');
    await expect(proxy(await request('/lead', undefined, { cookie: `${SESSION_COOKIE}=anything` }))).rejects.toThrow('SESSION_SECRET');
  });
});

describe('a signed-in role', () => {
  it('sends an advisor on /lead to the forbidden page', async () => {
    const response = await proxy(await request('/lead', 'advisor'));
    expect(rewrittenTo(response)).toBe('/forbidden');
    expect(response?.status).toBe(403);
  });

  it('lets an advisor into /advisor/case/4821', async () => {
    const response = await proxy(await request('/advisor/case/4821', 'advisor'));
    expect(passes(response)).toBe(true);
    expect(redirectedTo(response)).toBeNull();
    expect(rewrittenTo(response)).toBeNull();
  });

  it('does not let the browser cache a guarded page, allowed or not', async () => {
    expect((await proxy(await request('/advisor', 'advisor')))?.headers.get('cache-control')).toBe('no-store');
    expect((await proxy(await request('/lead', 'advisor')))?.headers.get('cache-control')).toBe('no-store');
  });

  const guarded = ['/advisor', '/advisor/case/4821', '/clinical', '/lead', '/owner', '/owner/criteria', '/planning', '/console', '/admin', '/admin/config'];
  it.each(ROLES.flatMap((role) => guarded.map((path) => [role, path] as const)))('%s on %s', async (role, path) => {
    const response = await proxy(await request(path, role));
    if (canAccess(role, path)) {
      expect(passes(response)).toBe(true);
    } else {
      expect(rewrittenTo(response)).toBe('/forbidden');
    }
  });

  it('gives a wall screen, a reporter and a link no staff page', async () => {
    for (const role of ['wall', 'reporter', 'anonymous-link', 'audit'] as Role[]) {
      for (const path of ['/advisor', '/clinical', '/lead', '/owner', '/planning', '/console', '/admin']) {
        expect(rewrittenTo(await proxy(await request(path, role)))).toBe('/forbidden');
      }
    }
  });

  it('takes the role from the cookie alone: a query string or a header cannot raise it', async () => {
    const attempts: [string, Record<string, string>][] = [
      ['/lead?role=lead', {}],
      ['/lead?role=lead&tenant=trust-b', {}],
      ['/lead', { 'x-role': 'lead', 'x-diucs-role': 'lead', authorization: 'Bearer lead' }],
    ];
    for (const [path, headers] of attempts) {
      expect(rewrittenTo(await proxy(await request(path, 'advisor', { headers })))).toBe('/forbidden');
    }
  });
});

describe('the content security policy (S01) on every guarded answer', () => {
  const nonceOf = (response: Response) => /'nonce-([^']+)'/.exec(response.headers.get('content-security-policy') ?? '')?.[1];

  it('is set on the redirect to sign-in, the 403 page and an allowed page, each with its own nonce', async () => {
    const redirect = await proxy(await request('/lead'));
    const forbidden = await proxy(await request('/lead', 'advisor'));
    const allowed = await proxy(await request('/advisor', 'advisor'));
    const nonces = [redirect, forbidden, allowed].map(nonceOf);
    for (const [index, response] of [redirect, forbidden, allowed].entries()) {
      expect(nonces[index]).toBeTruthy();
      expect(response.headers.get('content-security-policy')).toContain("frame-ancestors 'none'");
      expect(response.headers.get('strict-transport-security')).toBeTruthy();
    }
    expect(new Set(nonces).size).toBe(3);
  });

  it('hands the nonce to the page of a 403 and of an allowed guarded path', async () => {
    for (const response of [await proxy(await request('/lead', 'advisor')), await proxy(await request('/advisor', 'advisor'))]) {
      expect(response.headers.get('x-middleware-request-x-nonce')).toBe(nonceOf(response));
    }
  });

  it('overwrites a policy or nonce sent by the caller instead of passing it on', async () => {
    const response = await proxy(
      await request('/advisor', 'advisor', {
        headers: { 'x-nonce': 'attacker', 'content-security-policy': "script-src 'unsafe-inline'" },
      }),
    );
    expect(response.headers.get('x-middleware-request-x-nonce')).not.toBe('attacker');
    expect(response.headers.get('x-middleware-request-content-security-policy')).not.toContain('unsafe-inline');
    expect(response.headers.get('content-security-policy')).not.toContain('unsafe-inline');
  });
});

describe('the sign-in page may submit its form to the sign-in provider (W09, S01)', () => {
  // Chrome applies form-action to the redirect that answers a form post, so the page whose form
  // starts the sign-in must name the provider; no other page may.
  const formAction = (response: Response | undefined) =>
    (response?.headers.get('content-security-policy') ?? '')
      .split(';')
      .map((part) => part.trim())
      .find((part) => part.startsWith('form-action'));

  it('names the default Microsoft host on /sign-in', async () => {
    vi.stubEnv('ENTRA_AUTHORITY_HOST', '');
    expect(formAction(await proxy(await request('/sign-in')))).toBe("form-action 'self' https://login.microsoftonline.com");
  });

  it('names the configured host, and /sign-in with a query string too', async () => {
    vi.stubEnv('ENTRA_AUTHORITY_HOST', 'https://login.example.test');
    expect(formAction(await proxy(await request('/sign-in?next=%2Flead&error=failed')))).toBe(
      "form-action 'self' https://login.example.test",
    );
  });

  it('keeps self alone on every other path, guarded or not', async () => {
    vi.stubEnv('ENTRA_AUTHORITY_HOST', 'https://login.example.test');
    for (const path of ['/', '/screen', '/forbidden', '/sign-in/other', '/signin', '/lead', '/api/bff/auth/entra/start']) {
      expect(formAction(await proxy(await request(path)))).toBe("form-action 'self'");
    }
    expect(formAction(await proxy(await request('/lead', 'advisor')))).toBe("form-action 'self'");
  });

  it('falls back to self alone when the host setting is not an address the sign-in would accept', async () => {
    vi.stubEnv('ENTRA_AUTHORITY_HOST', 'https://login.example.test/path');
    expect(formAction(await proxy(await request('/sign-in')))).toBe("form-action 'self'");
  });
});

describe('matcher', () => {
  const patterns = config.matcher.map((m) => new RegExp(`^${m}$`));
  const covered = (path: string) => patterns.some((p) => p.test(path));

  it('covers every page path, so a rewritten or odd path still reaches the guard', () => {
    for (const path of ['/lead', '/advisor/case/4821', '//lead', '/%6Cead', '/', '/sign-in']) expect(covered(path)).toBe(true);
  });

  it('leaves out the static files Next serves', () => {
    for (const path of ['/_next/static/chunks/a.js', '/_next/image', '/favicon.ico']) expect(covered(path)).toBe(false);
  });
});

// The operator console (TEN-083): its pages are guarded by the OPERATOR session cookie and by nothing a
// tenant's person holds. No tenant role opens a console page and no operator opens a tenant's.

describe('the operator console pages', () => {
  const CONSOLE = `https://${OPERATOR_HOST}`;

  async function asOperator(path: string, role?: OperatorRole, init: { headers?: Record<string, string>; cookie?: string } = {}) {
    const headers = new Headers(init.headers);
    const cookie = init.cookie ?? (role ? `${OPERATOR_COOKIE}=${await sealOperatorSession(operatorSessionFor(role))}` : undefined);
    if (cookie) headers.set('cookie', cookie);
    return new NextRequest(`${CONSOLE}${path}`, { headers });
  }

  it('sends a request with no operator session to the console’s own sign-in, with the page to come back to', async () => {
    expect(redirectedTo(await proxy(await asOperator('/operator/audit')))).toBe('/operator/sign-in?next=%2Foperator%2Faudit');
    expect(redirectedTo(await proxy(await asOperator('/operator')))).toBe('/operator/sign-in?next=%2Foperator');
  });

  it('leaves the sign-in page open and does not need the session secret for it', async () => {
    vi.stubEnv('SESSION_SECRET', '');
    expect(passes(await proxy(await asOperator('/operator/sign-in?error=failed')))).toBe(true);
  });

  it('lets the operator into the tenants and the audit, and the support person into the support requests', async () => {
    for (const path of ['/operator', '/operator/tenants/trust-a', '/operator/tenants/new', '/operator/audit']) {
      expect(passes(await proxy(await asOperator(path, 'platform-operator'))), path).toBe(true);
    }
    expect(passes(await proxy(await asOperator('/operator', 'support')))).toBe(true);
    expect(passes(await proxy(await asOperator('/operator/support/new', 'support')))).toBe(true);
  });

  it('shows the forbidden page to a role that has no business on the page', async () => {
    for (const path of ['/operator/audit', '/operator/tenants/trust-a', '/operator/tenants/new']) {
      expect(rewrittenTo(await proxy(await asOperator(path, 'support'))), path).toBe('/forbidden');
    }
    expect(rewrittenTo(await proxy(await asOperator('/operator/support', 'platform-operator')))).toBe('/forbidden');
  });

  it('does not let a tenant’s person in, whatever their role: a tenant session is not an operator session', async () => {
    for (const role of ROLES) {
      const response = await proxy(await request('/operator', role));
      expect(redirectedTo(response), role).toBe('/operator/sign-in?next=%2Foperator');
    }
    const sealed = await sealSession(sessionFor('tenant-admin'));
    const renamed = await proxy(await asOperator('/operator/audit', undefined, { cookie: `${OPERATOR_COOKIE}=${sealed}` }));
    expect(redirectedTo(renamed)).toBe('/operator/sign-in?next=%2Foperator%2Faudit');
  });

  it('does not let an operator into a tenant’s page: the operator cookie is no tenant session', async () => {
    for (const path of ['/lead', '/admin', '/advisor', '/console']) {
      const response = await proxy(await asOperator(path, 'platform-operator', { cookie: `${OPERATOR_COOKIE}=${await sealOperatorSession(operatorSessionFor('platform-operator'))}` }));
      expect(redirectedTo(response), path).toBe(`/sign-in?next=${encodeURIComponent(path)}`);
    }
  });

  it('does not let an operator session made for another host in', async () => {
    const sealed = await sealOperatorSession(operatorSessionFor('platform-operator', { host: 'other.example.test' }));
    expect(redirectedTo(await proxy(await asOperator('/operator', undefined, { cookie: `${OPERATOR_COOKIE}=${sealed}` })))).toBe('/operator/sign-in?next=%2Foperator');
  });

  it('does not let the browser cache a console page, and names the provider only on the console’s sign-in page', async () => {
    expect((await proxy(await asOperator('/operator', 'platform-operator')))?.headers.get('cache-control')).toBe('no-store');
    vi.stubEnv('ENTRA_AUTHORITY_HOST', 'https://login.example.test');
    const formAction = (response: Response | undefined) =>
      (response?.headers.get('content-security-policy') ?? '').split(';').map((part) => part.trim()).find((part) => part.startsWith('form-action'));
    expect(formAction(await proxy(await asOperator('/operator/sign-in')))).toBe("form-action 'self' https://login.example.test");
    expect(formAction(await proxy(await asOperator('/operator', 'platform-operator')))).toBe("form-action 'self'");
  });
});
