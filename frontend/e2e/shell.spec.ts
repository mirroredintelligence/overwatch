import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { signIn } from './support/session';
import { SITE_URL } from './support/env';
import { TOKEN_ORG_A } from './support/tokens';

// The staff shell and the brand, as a browser sees them (components/shell, components/brand): the header
// every staff area carries, the logo on the pages that had none, the splash at the launch of the installed
// app, and the icons the head names. The stand-in back end serves no lead or clinical data, so the pages
// below show their own "could not load" first screens; the header is what is checked.

async function accessible(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  expect(results.violations).toEqual([]);
}

const ROLE_HOMES = [
  { role: 'advisor', path: '/advisor', label: 'Advisor', link: 'Wall board' },
  { role: 'clinical', path: '/clinical', label: 'Clinical advisor', link: 'Requests' },
  { role: 'lead', path: '/lead', label: 'Shift lead', link: 'Registrations' },
  { role: 'exec', path: '/planning', label: 'Planning', link: 'This week' },
] as const;

for (const { role, path, label, link } of ROLE_HOMES) {
  test(`the ${role} header has the logo, the role, its navigation, Help and Sign out, and passes axe`, async ({ page }) => {
    await signIn(page.context(), SITE_URL, role, TOKEN_ORG_A);
    await page.goto(path);
    const header = page.getByRole('banner');
    await expect(header.getByRole('link', { name: 'Overwatch home' })).toHaveAttribute('href', path);
    await expect(header.getByRole('img', { name: 'Overwatch' })).toBeVisible();
    await expect(header.getByText(label, { exact: true })).toBeVisible();
    await expect(header.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: link })).toBeVisible();
    await expect(header.getByRole('link', { name: 'Help' })).toHaveAttribute('href', '/help');
    await expect(header.getByRole('button', { name: 'Sign out' })).toBeVisible();
    // The home is the current page, and only one item says so.
    await expect(header.locator('a[aria-current="page"]')).toHaveCount(1);
    await accessible(page);
  });
}

test('the shift lead header marks the page the lead is on', async ({ page }) => {
  await signIn(page.context(), SITE_URL, 'lead', TOKEN_ORG_A);
  await page.goto('/lead/registrations');
  const current = page.getByRole('banner').locator('a[aria-current="page"]');
  await expect(current).toHaveText('Registrations');
});

test('the header stays on one line of controls at phone width, with nothing scrolling sideways', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await signIn(page.context(), SITE_URL, 'lead', TOKEN_ORG_A);
  await page.goto('/lead');
  await expect(page.getByRole('banner')).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  await accessible(page);
});

test('a page with nobody signed in has the logo and Help only', async ({ page }) => {
  await page.goto('/register');
  const header = page.getByRole('banner');
  await expect(header.getByRole('img', { name: 'Overwatch' })).toBeVisible();
  await expect(header.getByRole('link', { name: 'Help' })).toBeVisible();
  await expect(header.getByRole('navigation')).toHaveCount(0);
  await expect(header.getByRole('button', { name: 'Sign out' })).toHaveCount(0);
  await accessible(page);
});

test('the reporter PIN page carries the logo', async ({ page }) => {
  await page.goto('/app/pin');
  await expect(page.getByRole('banner').getByRole('img', { name: 'Overwatch' })).toBeVisible();
});

test('the wall pairing page has the reversed logo on a dark header', async ({ page }) => {
  await page.goto('/screen/pair');
  const logo = page.getByRole('heading', { level: 1 }).getByRole('img', { name: 'Overwatch' });
  await expect(logo).toHaveAttribute('src', /overwatch-logo-reversed\.svg/);
  const background = await page.locator('main > header').evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(background).toBe('rgb(20, 35, 43)');
  await expect(page.getByRole('heading', { level: 1 })).toHaveAccessibleName('Overwatch wall screen');
});

test('the head names the manifest, the tab icon and the iOS icon, and each one is served as a PNG', async ({ page, request }) => {
  await page.goto('/');
  const manifest = await page.locator('link[rel="manifest"]').getAttribute('href');
  expect(manifest).toBe('/manifest.webmanifest');
  const body = (await (await request.get('/manifest.webmanifest')).json()) as { name: string; short_name: string };
  expect([body.name, body.short_name]).toEqual(['Overwatch', 'Overwatch']);
  for (const rel of ['icon', 'apple-touch-icon']) {
    const href = await page.locator(`link[rel="${rel}"]`).first().getAttribute('href');
    expect(href, rel).toBeTruthy();
    const answer = await request.get(href as string);
    expect(answer.status(), rel).toBe(200);
    expect(answer.headers()['content-type'], rel).toContain('image/png');
  }
  await expect(page.locator('meta[name="apple-mobile-web-app-title"]')).toHaveAttribute('content', 'Overwatch');
});

// The splash runs only as an installed app; a test browser is a tab, so the display mode is faked.
async function asInstalledApp(page: Page) {
  await page.addInitScript(() => {
    const real = window.matchMedia.bind(window);
    window.matchMedia = (query: string) =>
      query === '(display-mode: standalone)' ? ({ ...real('(min-width: 0px)'), matches: true, media: query } as MediaQueryList) : real(query);
  });
}

test('the splash shows once at the launch of the installed app, and never blocks the page', async ({ page }) => {
  await asInstalledApp(page);
  await page.goto('/sign-in');
  const splash = page.locator('[data-el="LAUNCH-SPLASH"]');
  await expect(splash).toBeAttached();
  // The page under it takes the click: the splash lets it through.
  await expect(page.getByRole('button', { name: /Sign in/ }).first()).toBeEnabled();
  const topmost = await page.getByRole('heading', { level: 2, name: 'Sign in' }).evaluate((el) => {
    const box = el.getBoundingClientRect();
    return document.elementFromPoint(box.x + 2, box.y + 2) === el;
  });
  expect(topmost || (await splash.evaluate((el) => getComputedStyle(el).pointerEvents)) === 'none').toBe(true);
  await expect(splash).toHaveCount(0, { timeout: 6000 });
  // A second page in the same session does not show it again.
  await page.goto('/');
  await page.waitForTimeout(500);
  await expect(splash).toHaveCount(0);
});

test('the splash is not shown in a browser tab', async ({ page }) => {
  await page.goto('/sign-in');
  await page.waitForTimeout(500);
  await expect(page.locator('[data-el="LAUNCH-SPLASH"]')).toHaveCount(0);
});

test('with reduced motion the splash is a short still of the finished logo', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await asInstalledApp(page);
  await page.goto('/sign-in');
  const splash = page.locator('[data-el="LAUNCH-SPLASH"]');
  await expect(splash).toBeAttached();
  await expect(splash).toHaveCount(0, { timeout: 2000 });
});
