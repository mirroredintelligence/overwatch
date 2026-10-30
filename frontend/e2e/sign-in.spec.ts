import AxeBuilder from '@axe-core/playwright';
import { expect, test, type BrowserContext, type Page } from '@playwright/test';
import { ENTRA_COOKIE, PERSONAS } from './support/oidc';
import { ENTRA_HOST } from './support/env';

// Staff sign-in in a real browser, against the fake Entra provider (e2e/support/oidc.ts) on another
// site (127.0.0.1, where the site is localhost), so the return from the provider is a cross-site
// navigation as it is from Microsoft. Entra itself is not reached: this build has no credential for it.

async function choose(context: BrowserContext, persona: keyof typeof PERSONAS) {
  await context.addCookies([{ name: ENTRA_COOKIE, value: persona, url: ENTRA_HOST }]);
}

async function signInAs(page: Page, persona: keyof typeof PERSONAS, from = '/sign-in') {
  await choose(page.context(), persona);
  await page.goto(from);
  if (new URL(page.url()).pathname !== '/sign-in') return;
  await page.getByRole('button', { name: 'Sign in with your Trust account' }).click();
}

async function sessionRole(page: Page): Promise<string | null> {
  const response = await page.request.get('/api/bff/session');
  return response.ok() ? ((await response.json()) as { role: string }).role : null;
}

test('signs an advisor in and lands on the advisor home with the strict session cookie sent', async ({ page }) => {
  await signInAs(page, 'advisor');

  await expect(page).toHaveURL(/\/advisor$/);
  // The session cookie was set on the return from another site and still reached the next request.
  expect(await sessionRole(page)).toBe('advisor');
});

test('sets the session cookie HttpOnly and SameSite Strict, and leaves no transaction cookie behind', async ({ page }) => {
  await signInAs(page, 'advisor');
  await expect(page).toHaveURL(/\/advisor$/);

  const cookies = await page.context().cookies();
  const session = cookies.find((c) => c.name === 'diucs_session');
  expect(session).toMatchObject({ httpOnly: true, sameSite: 'Strict', path: '/' });
  expect(session!.expires).toBeGreaterThan(Date.now() / 1000 + 7 * 3600);
  expect(cookies.find((c) => c.name === 'diucs_oidc')).toBeUndefined();
  // Not readable by the page.
  expect(await page.evaluate(() => document.cookie)).not.toContain('diucs_session');
});

test('asks the provider with PKCE and sends no tenant, and the browser never holds a token', async ({ page, request }) => {
  await signInAs(page, 'advisor');
  await expect(page).toHaveURL(/\/advisor$/);

  const recorded = (await (await request.get(`${ENTRA_HOST}/__requests`)).json()) as {
    endpoint: string;
    params: Record<string, string>;
  }[];
  const authorize = recorded.filter((r) => r.endpoint === 'authorize').at(-1)!;
  expect(authorize.params.code_challenge_method).toBe('S256');
  expect(authorize.params.scope).toBe('openid');
  expect(Object.keys(authorize.params).join(' ')).not.toMatch(/tenant|login_hint/);

  const storage = await page.evaluate(() => JSON.stringify([localStorage, sessionStorage]));
  expect(storage).not.toMatch(/eyJ/);
  expect(await page.content()).not.toMatch(/eyJ[A-Za-z0-9_-]{10,}\./);
});

test('goes back to the page asked for after signing in', async ({ page }) => {
  await choose(page.context(), 'lead');
  await page.goto('/lead');
  await expect(page).toHaveURL(/\/sign-in\?next=%2Flead$/);

  await page.getByRole('button', { name: 'Sign in with your Trust account' }).click();

  await expect(page).toHaveURL(/\/lead$/);
  expect(await sessionRole(page)).toBe('lead');
});

test('shows the access message and sets no session when the account has no DIUCS role', async ({ page }) => {
  await signInAs(page, 'no-role');

  await expect(page).toHaveURL(/\/sign-in\?error=no-access$/);
  await expect(
    page.getByText('Your account does not have access to DIUCS capacity. Ask your shift lead to check your access.'),
  ).toBeVisible();
  expect(await sessionRole(page)).toBeNull();
});

test('gives the support role to nobody who signs in through the staff door', async ({ page }) => {
  await signInAs(page, 'support-from-a-customer');

  await expect(page).toHaveURL(/\/sign-in\?error=no-access$/);
  expect(await sessionRole(page)).toBeNull();
});

for (const persona of ['unbound-directory', 'other-organisation'] as const) {
  test(`shows the one access message to a person from a directory this host’s tenant has not bound (${persona})`, async ({ page }) => {
    await signInAs(page, persona);

    await expect(page).toHaveURL(/\/sign-in\?error=no-access$/);
    expect(await sessionRole(page)).toBeNull();
  });
}

test('refuses a token with the wrong nonce', async ({ page }) => {
  await signInAs(page, 'forged-nonce');

  await expect(page).toHaveURL(/\/sign-in\?error=failed$/);
  await expect(page.getByText('We could not sign you in.')).toBeVisible();
  expect(await sessionRole(page)).toBeNull();
});

test('shows the forbidden page, with a 403, to an advisor on the lead page', async ({ page }) => {
  await signInAs(page, 'advisor');
  await expect(page).toHaveURL(/\/advisor$/);

  const response = await page.goto('/lead');

  expect(response?.status()).toBe(403);
  await expect(page.getByRole('heading', { name: 'You do not have access to this page.' })).toBeVisible();
});

test('lets a lead into the advisor case page, and not into the clinical page', async ({ page }) => {
  await signInAs(page, 'lead');
  await expect(page).toHaveURL(/\/lead$/);

  expect((await page.goto('/advisor/case/4821'))?.status()).not.toBe(403);
  expect((await page.goto('/clinical'))?.status()).toBe(403);
});

test('sends a signed-out visitor to sign-in, and does so again after sign-out', async ({ page }) => {
  await page.goto('/advisor');
  await expect(page).toHaveURL(/\/sign-in\?next=%2Fadvisor$/);

  await signInAs(page, 'advisor');
  await expect(page).toHaveURL(/\/advisor$/);

  const me = await (await page.request.get('/api/bff/session')).json();
  const out = await page.request.delete('/api/bff/session', { headers: { 'X-CSRF-Token': me.csrfToken } });
  expect(out.status()).toBe(204);

  await page.goto('/advisor');
  await expect(page).toHaveURL(/\/sign-in\?next=%2Fadvisor$/);
});

test('sends an expired or removed session cookie to sign-in', async ({ page }) => {
  await signInAs(page, 'advisor');
  await expect(page).toHaveURL(/\/advisor$/);
  await page.context().clearCookies({ name: 'diucs_session' });

  await page.goto('/advisor');

  await expect(page).toHaveURL(/\/sign-in\?next=%2Fadvisor$/);
});

test('ignores ?role= and ?tenant= for what a person may see', async ({ page }) => {
  await signInAs(page, 'advisor');
  await expect(page).toHaveURL(/\/advisor$/);

  const response = await page.goto('/lead?role=lead&tenant=trust-b');

  expect(response?.status()).toBe(403);
});

for (const [name, path] of [
  ['sign-in', '/sign-in'],
  ['sign-in for a clinical advisor', '/sign-in?role=clinical'],
  ['sign-in with the access message', '/sign-in?error=no-access'],
  ['forbidden', '/forbidden'],
] as const) {
  test(`has no axe violations on the ${name} page, with colour contrast`, async ({ page }) => {
    await page.goto(path);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

    const results = await new AxeBuilder({ page }).analyze();

    expect(results.violations).toEqual([]);
  });
}

test('shows the clinical note only for ?role=clinical, and reads at phone width without sideways scroll', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 });
  await page.goto('/sign-in?role=clinical');
  await expect(
    page.getByText('Clinical advisors see case details, so this uses staff sign-in, not a texted code.'),
  ).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

  await page.goto('/sign-in');
  await expect(page.getByText('Clinical advisors see case details')).toHaveCount(0);
});
