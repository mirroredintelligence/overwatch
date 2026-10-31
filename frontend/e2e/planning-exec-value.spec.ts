import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { SITE_URL } from './support/env';
import { signIn } from './support/session';
import { TOKEN_ORG_A } from './support/tokens';

// The planning view, the executive's app, the value case, the product tour, the lessons and the help page
// (PlanningView, ExecApp1, ExecApp2, ValueCase, TourPhone1, TourRoles and TrainingPhone artboards), as a
// browser sees them, each with axe (WCAG 2.2 A and AA) and, where the artboard is a phone, at phone width
// with no sideways scroll. The executive's routes are answered by the stand-in back end (e2e/support/exec.ts).

const PHONE = { width: 375, height: 812 };

async function accessible(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag22aa']).analyze();
  expect(results.violations).toEqual([]);
}

/** The page is no wider than the screen: nothing scrolls sideways. */
async function noSidewaysScroll(page: Page) {
  const widths = await page.evaluate(() => ({ page: document.documentElement.scrollWidth, screen: document.documentElement.clientWidth }));
  expect(widths.page).toBeLessThanOrEqual(widths.screen);
}

test.describe('planning view (PlanningView)', () => {
  test('shows the headline cards, the flows, the heat grid and the notes, and passes axe', async ({ page }) => {
    await signIn(page.context(), SITE_URL, 'exec', TOKEN_ORG_A);
    await page.goto('/planning/flows');
    await expect(page.getByRole('heading', { level: 1, name: 'Right-sizing: where capacity ran out' })).toBeVisible();

    const cards = page.getByRole('list', { name: 'Headline figures' }).getByRole('listitem');
    await expect(cards).toHaveCount(3, { timeout: 20_000 });
    await expect(cards.nth(0)).toContainText('640');
    await expect(cards.nth(1)).toContainText('18% of referrals');
    await expect(cards.nth(2)).toContainText('went to another suitable service');

    await expect(page.getByRole('heading', { name: 'Where they went when the best fit was full' })).toBeVisible();
    await expect(page.getByRole('table', { name: /Where they went/ }).getByText('fewer than 10')).toBeVisible();
    const heat = page.getByRole('table', { name: /by day and time/ });
    await expect(heat.getByRole('columnheader')).toHaveCount(8);
    await expect(page.getByText('Busiest: Thursday 12:00 to 18:00 (18)')).toBeVisible();
    await expect(page.getByText('Who acts on these findings: [owner to be agreed].')).toBeVisible();
    await expect(page.getByRole('link', { name: 'Export table (CSV)' })).toHaveAttribute('href', /\/api\/bff\/planning\/export\?period=90d&need=all/);
    await accessible(page);
  });

  test('has no sideways scroll at phone width', async ({ page }) => {
    await page.setViewportSize(PHONE);
    await signIn(page.context(), SITE_URL, 'exec', TOKEN_ORG_A);
    await page.goto('/planning/flows');
    // The first read compiles the route in the dev server: give it longer than the default.
    await expect(page.getByRole('list', { name: 'Headline figures' })).toBeVisible({ timeout: 20_000 });
    await noSidewaysScroll(page);
  });
});

test.describe('the executive’s app (ExecApp1, ExecApp2)', () => {
  test('home counts the services and lists what needs attention, at phone width too', async ({ page }) => {
    await page.setViewportSize(PHONE);
    await signIn(page.context(), SITE_URL, 'exec', TOKEN_ORG_A);
    await page.goto('/planning');
    await expect(page.getByRole('heading', { level: 2, name: /^Needs attention \(\d+\)$/ })).toBeVisible();
    await expect(page.getByRole('region', { name: 'Counts by status' }).getByRole('listitem')).toHaveCount(5);
    await expect(page.getByRole('link', { name: 'See all services' })).toBeVisible();
    await noSidewaysScroll(page);
    await accessible(page);
  });

  test('a service shows its alert and whether escalation is in place', async ({ page }) => {
    await page.setViewportSize(PHONE);
    await signIn(page.context(), SITE_URL, 'exec', TOKEN_ORG_A);
    await page.goto('/planning/services/svc-ucr-west');
    await expect(page.getByRole('heading', { level: 1, name: 'UCR West' })).toBeVisible();
    await expect(page.getByText('Alert', { exact: true })).toBeVisible();
    await expect(page.getByText(/^New, alerted \d\d:\d\d$/)).toBeVisible();
    await expect(page.getByText('Escalation in place')).toBeVisible();
    await expect(page.getByRole('link', { name: 'Back to alerts' })).toBeVisible();
    await noSidewaysScroll(page);
    await accessible(page);
  });

  test('this week shows four figures as tiles and the time back as an estimate', async ({ page }) => {
    await page.setViewportSize(PHONE);
    await signIn(page.context(), SITE_URL, 'exec', TOKEN_ORG_A);
    await page.goto('/planning/week');
    const tiles = page.getByRole('list', { name: 'Figures for the week' }).getByRole('listitem');
    await expect(tiles).toHaveCount(4);
    await expect(tiles.nth(0)).toContainText('640');
    await expect(tiles.nth(1)).toContainText('18%');
    await expect(page.getByRole('heading', { name: 'Time back (estimate)' })).toBeVisible();
    await expect(page.getByText('Counts under 10 are hidden. Outcomes are not shown yet.')).toBeVisible();
    await noSidewaysScroll(page);
    await accessible(page);
  });

  test('alerts has Open, Acknowledged and Closed, says acknowledging does not change the board, and moves an acknowledged alert', async ({ page }) => {
    await page.setViewportSize(PHONE);
    await signIn(page.context(), SITE_URL, 'exec', TOKEN_ORG_A);
    await page.goto('/planning/alerts');
    await expect(page.getByRole('tab', { name: 'Open (1)' })).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByText('Acknowledging tells others it is being handled. It does not change the board.')).toBeVisible();
    await noSidewaysScroll(page);
    await accessible(page);

    await page.getByRole('tab', { name: 'Acknowledged' }).click();
    await expect(page.getByText(/Acknowledged by you \d\d:\d\d/)).toBeVisible();
    await page.getByRole('tab', { name: 'Open (1)' }).click();
    await page.getByRole('button', { name: 'Acknowledge' }).click();
    await expect(page.getByText('No open alerts.')).toBeVisible();
  });

  test('set-up runs from the welcome to the alerts and on to escalation, at phone width', async ({ page }) => {
    await page.setViewportSize(PHONE);
    await signIn(page.context(), SITE_URL, 'exec', TOKEN_ORG_A);
    await page.goto('/planning/setup');
    await expect(page.getByRole('heading', { level: 1, name: 'The whole system in your pocket' })).toBeVisible();
    await noSidewaysScroll(page);
    await page.getByRole('button', { name: 'Choose my alerts' }).click();
    await expect(page.getByRole('switch', { name: 'A service goes over capacity' })).toBeVisible();
    await noSidewaysScroll(page);
    await accessible(page);
    await page.getByRole('button', { name: 'Save my alerts' }).click();
    await expect(page.getByRole('heading', { level: 1, name: 'If nobody acknowledges' })).toBeVisible();
    await expect(page.getByText('The ladder: you, then your deputy, then the shift lead by phone.')).toBeVisible();
    await noSidewaysScroll(page);
    await accessible(page);
  });
});

test.describe('the value case (ValueCase)', () => {
  test('is a public page with the promises, the measures and the rules, and passes axe', async ({ page }) => {
    await page.goto('/value');
    await expect(page.getByRole('heading', { level: 1, name: 'What we promise, and how we prove it' })).toBeVisible();
    for (const group of ['Services', 'Call advisors and shift leads', 'Clinical advisors', 'COOs and ICB']) {
      await expect(page.getByRole('heading', { level: 2, name: group })).toBeVisible();
    }
    await expect(page.getByRole('table', { name: 'What we measure to show the value' }).getByText('[to agree]')).toHaveCount(6);
    await expect(page.getByText(/No saving is claimed before the baseline is measured/)).toBeVisible();
    await expect(page.getByRole('link', { name: 'A one-minute product tour by role' })).toHaveAttribute('href', '/tour');
    await expect(page.locator('meta[name="robots"]')).toHaveAttribute('content', /noindex/);
    await accessible(page);
  });

  test('has no sideways scroll at phone width: the table scrolls inside its own box', async ({ page }) => {
    await page.setViewportSize(PHONE);
    await page.goto('/value');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await noSidewaysScroll(page);
  });
});

test.describe('the product tour (TourPhone1, TourRoles) at phone width', () => {
  test.use({ viewport: PHONE });

  test('walks the reporter through the six steps', async ({ page }) => {
    await page.goto('/tour');
    await page.getByRole('button', { name: 'Take the 1-minute tour' }).click();
    await page.getByRole('button', { name: 'I report capacity for a service' }).click();
    await page.getByRole('button', { name: 'Continue' }).click();
    await expect(page.getByRole('heading', { level: 1, name: 'Your day, before and after' })).toBeVisible();
    await expect(page.getByText('A phone call today takes [x] minutes. We measure it in the pilot.')).toBeVisible();
    await noSidewaysScroll(page);
    await accessible(page);
    await page.getByRole('button', { name: 'Next', exact: true }).click();
    await expect(page.getByRole('heading', { level: 1, name: 'How it works' })).toBeVisible();
    await noSidewaysScroll(page);
    await page.getByRole('button', { name: 'Next', exact: true }).click();
    await expect(page.getByRole('heading', { level: 1, name: 'Practice update' })).toBeVisible();
    await page.getByRole('button', { name: 'Skip practice' }).click();
    await expect(page.getByRole('heading', { level: 1, name: 'Your first week' })).toBeVisible();
    await noSidewaysScroll(page);
    await accessible(page);
  });

  for (const [choice, heading, action, href] of [
    ['I take calls as an advisor', 'For call advisors', 'Try a practice call', null],
    ['I am a shift lead', 'For shift leads', 'Invite a reporter', '/lead/reporters/invite'],
    ['I am a clinical advisor', 'For clinical advisors', 'Go on duty', '/clinical'],
    ['I am a COO or ICB lead', 'For COOs and ICB leads', 'Choose my alerts', '/planning/setup'],
  ] as const) {
    test(`shows what changes for: ${choice}`, async ({ page }) => {
      await page.goto('/tour?step=role');
      await page.getByRole('button', { name: choice }).click();
      await page.getByRole('button', { name: 'Continue' }).click();
      await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible();
      await expect(page.getByRole('list', { name: 'Today' })).toBeVisible();
      await expect(page.getByRole('list', { name: 'With Overwatch' })).toBeVisible();
      if (href === null) await expect(page.getByRole('button', { name: action })).toBeVisible();
      else await expect(page.getByRole('link', { name: action })).toHaveAttribute('href', href);
      await expect(page.getByRole('link', { name: 'Skip' })).toHaveAttribute('href', '/');
      await noSidewaysScroll(page);
      await accessible(page);
    });
  }
});

test.describe('training and help (TrainingPhone) at phone width', () => {
  test.use({ viewport: PHONE });

  test('the library, a lesson, practice mode and the help panel fit the screen', async ({ page }) => {
    await page.goto('/learn');
    await expect(page.getByRole('heading', { level: 1, name: '2-minute lessons' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Start the next lesson' })).toBeVisible();
    await expect(page.getByRole('heading', { level: 2, name: 'Need a hand?' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Read the one-page guide' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Report a problem' })).toHaveAttribute('href', '/help/problem');
    await noSidewaysScroll(page);
    await accessible(page);

    await page.getByRole('link', { name: /Correct a figure/ }).click();
    await expect(page.getByRole('heading', { level: 1, name: /Correct a figure/ })).toBeVisible();
    await noSidewaysScroll(page);
    await accessible(page);

    await page.getByRole('link', { name: 'Try it in practice mode' }).click();
    await expect(page.getByText('Practice. Nothing is sent.')).toBeVisible();
    await noSidewaysScroll(page);
    await accessible(page);
  });

  test('the help page offers the four ways to get help and the reports', async ({ page }) => {
    await signIn(page.context(), SITE_URL, 'advisor', TOKEN_ORG_A);
    await page.goto('/help');
    await expect(page.getByRole('heading', { level: 1, name: 'Help' })).toBeVisible();
    await expect(page.getByRole('heading', { level: 2, name: 'Need a hand?' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Report a safety concern' })).toBeVisible();
    await noSidewaysScroll(page);
    await accessible(page);
  });
});
