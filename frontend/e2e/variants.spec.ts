import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import AxeBuilder from '@axe-core/playwright';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { BACKEND_PORT, SITE_URL } from './support/env';
import { signIn } from './support/session';
import { LIVE_SURGE_PREFIX, TOKEN_FOREIGN_ENTRY, TOKEN_QUIET, TOKEN_SURGE } from './support/tokens';

// The wall board variants in a real browser (W07): the "System under pressure"
// banner and the over-capacity and pending tiles (BoardSurge), the out-of-hours
// tiles (BoardQuiet), and the rule that a stale board never looks current. Axe
// runs with colour contrast at five sizes. Screenshots (sample data only) go to
// test-results/screenshots, or the folder named by BOARD_SHOT_DIR (the ones kept as
// evidence: ../docs/delivery/evidence/W07).

const HERE = fileURLToPath(new URL('.', import.meta.url));
const SHOTS = resolve(HERE, '..', process.env.BOARD_SHOT_DIR ?? 'test-results/screenshots');
mkdirSync(SHOTS, { recursive: true });

const BACKEND = `http://127.0.0.1:${BACKEND_PORT}`;
const SIZES = [
  { name: 'wall-1920x1080', width: 1920, height: 1080 },
  { name: 'laptop-1280x720', width: 1280, height: 720 },
  { name: 'zoom-200-percent-960x540', width: 960, height: 540 },
  { name: 'tablet-768x1024', width: 768, height: 1024 },
  { name: 'phone-390x844', width: 390, height: 844 },
] as const;

async function openBoard(page: Page, token: string) {
  await signIn(page.context(), SITE_URL, 'wall', token);
  await page.goto('/screen');
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
}

const tiles = (page: Page) => page.locator('[data-el="WALL-TILE"]');
const pressure = (page: Page) => page.locator('[data-el="WALL-PRESSURE-BANNER"]');

async function checkAxe(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  expect(results.violations).toEqual([]);
}

async function noHorizontalScroll(page: Page) {
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
}

test.describe('the surge board', () => {
  test('shows the pressure banner above the tiles, with the over-capacity and pending tiles', async ({ page }) => {
    await openBoard(page, TOKEN_SURGE);

    await expect(pressure(page)).toContainText('System under pressure');
    await expect(pressure(page)).toContainText('All 9 services are limited, not accepting or over capacity.');
    await expect(tiles(page)).toHaveCount(9);
    const home = page.locator('[data-service-id="svc-hospital-at-home"]');
    await expect(home).toContainText('Over capacity');
    await expect(home.locator('[data-el="WALL-TILE-NUMBER"]')).toHaveText('+4');
    await expect(home).toContainText('Used 16 of 12 · 1 pending');
    await expect(page.locator('[data-el="WALL-TILE-PENDING"]')).toHaveCount(2);
    await expect(page.getByText('Last known', { exact: true })).toHaveCount(0);

    const bannerBottom = await pressure(page).evaluate((el) => el.getBoundingClientRect().bottom);
    const gridTop = await page.getByRole('list', { name: 'Services' }).evaluate((el) => el.getBoundingClientRect().top);
    expect(bannerBottom).toBeLessThanOrEqual(gridTop);
  });

  for (const size of SIZES) {
    test.describe(`at ${size.width} by ${size.height}`, () => {
      test.use({ viewport: { width: size.width, height: size.height } });

      test('has no horizontal scroll, passes axe with colour contrast, and is photographed', async ({ page }) => {
        await openBoard(page, TOKEN_SURGE);

        await expect(pressure(page)).toBeVisible();
        await noHorizontalScroll(page);
        await checkAxe(page);
        await page.screenshot({ path: resolve(SHOTS, `surge-${size.name}.png`), fullPage: true });
      });
    });
  }
});

test.describe('the quiet board', () => {
  test('shows six out-of-hours tiles that say when they reopen, and no pressure banner', async ({ page }) => {
    await openBoard(page, TOKEN_QUIET);

    const closed = page.locator('[data-el="WALL-TILE"][data-status="out-of-hours"]');
    await expect(closed).toHaveCount(6);
    await expect(pressure(page)).toHaveCount(0);
    for (const tile of await closed.all()) {
      await expect(tile).toContainText('Out of hours');
      await expect(tile).toContainText('Closed overnight');
      await expect(tile).toContainText(/Reopens \d\d:\d\d( tomorrow| [A-Z][a-z]+)?/);
      await expect(tile.locator('[data-el="WALL-TILE-NUMBER"]')).toHaveText('0');
      await expect(tile.locator('[data-shape="moon"]')).toHaveCount(1);
    }
  });

  for (const size of SIZES) {
    test.describe(`at ${size.width} by ${size.height}`, () => {
      test.use({ viewport: { width: size.width, height: size.height } });

      test('has no horizontal scroll, passes axe with colour contrast, and is photographed', async ({ page }) => {
        await openBoard(page, TOKEN_QUIET);

        await expect(page.locator('[data-status="out-of-hours"]').first()).toBeVisible();
        await noHorizontalScroll(page);
        await checkAxe(page);
        await page.screenshot({ path: resolve(SHOTS, `quiet-${size.name}.png`), fullPage: true });
      });
    });
  }
});

test('refuses a payload with a foreign organisation part, and shows no tile', async ({ page }) => {
  await signIn(page.context(), SITE_URL, 'wall', TOKEN_FOREIGN_ENTRY);
  await page.goto('/screen');

  await expect(page.getByRole('alert').filter({ hasText: 'Board unavailable' })).toBeVisible();
  await expect(tiles(page)).toHaveCount(0);
  const text = await page.locator('body').innerText();
  expect(text).not.toContain('Neighbouring');
  expect(text).not.toContain('UCR West');
});

test.describe('a surge board that goes stale', () => {
  const token = `${LIVE_SURGE_PREFIX}${Math.random().toString(36).slice(2, 8)}`;

  async function control(request: APIRequestContext, change: Record<string, unknown>) {
    const response = await request.post(`${BACKEND}/__control/${encodeURIComponent(token)}`, { data: change });
    expect(response.ok()).toBe(true);
  }

  async function state(request: APIRequestContext) {
    const response = await request.get(`${BACKEND}/__state/${encodeURIComponent(token)}`);
    return (await response.json()) as { streamOpens: number; streamRefusals: number };
  }

  test('loses the pressure banner and every variant detail, and says Last known, never current', async ({ page, request }) => {
    await signIn(page.context(), SITE_URL, 'wall', token);
    await page.clock.install();
    await page.goto('/screen');
    await expect(pressure(page)).toBeVisible();
    await expect.poll(async () => (await state(request)).streamOpens, { timeout: 15_000 }).toBeGreaterThan(0);

    const refusals = (await state(request)).streamRefusals;
    await control(request, { mode: 'down', streamDown: true, drop: true });
    await expect.poll(async () => (await state(request)).streamRefusals, { timeout: 15_000 }).toBeGreaterThan(refusals);
    await page.clock.fastForward(65_000);

    await expect(page.locator('[data-el="WALL-OFFLINE-BANNER"]')).toContainText('Tool offline since');
    await expect(pressure(page)).toHaveCount(0);
    await expect(page.locator('[data-el="WALL-TILE-PENDING"]')).toHaveCount(0);
    for (const status of await tiles(page).evaluateAll((nodes) => nodes.map((n) => n.getAttribute('data-status')))) {
      expect(status).toBe('last-known');
    }
    // The key under the grid names every status, so look at the tiles and above them only.
    const tileText = (await tiles(page).allInnerTexts()).join('\n');
    expect(tileText).not.toMatch(/pending|Over capacity|Out of hours/);
    await expect(page.getByText('System under pressure')).toHaveCount(0);
    await checkAxe(page);
    await page.screenshot({ path: resolve(SHOTS, 'surge-last-known-wall-1920x1080.png'), fullPage: true });

    await control(request, { mode: 'ok', streamDown: false });
    await page.clock.fastForward(65_000);
    await expect(pressure(page)).toBeVisible();
    await expect(page.locator('[data-el="WALL-OFFLINE-BANNER"]')).toHaveCount(0);
  });
});
