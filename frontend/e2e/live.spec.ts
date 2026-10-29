import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import AxeBuilder from '@axe-core/playwright';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { BACKEND_PORT } from './support/env';
import { signIn } from './support/session';
import { LIVE_TOKEN_PREFIX } from './support/tokens';

// The wall board kept current, in a real browser, against a stand-in back end
// that can drop its stream, fail, answer with rubbish and send events. Each test
// has its own token, so its own back end state. Time-driven steps use the
// browser's fake clock (page.clock), so a minute is not a minute.
// Screenshots (sample data only): test-results/screenshots, or the folder named
// by BOARD_SHOT_DIR (the ones kept as evidence: ../docs/delivery/evidence/W06).

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

function tokenFor(testName: string): string {
  return `${LIVE_TOKEN_PREFIX}${testName.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}-${Math.random().toString(36).slice(2, 8)}`;
}

async function control(request: APIRequestContext, token: string, change: Record<string, unknown>) {
  const response = await request.post(`${BACKEND}/__control/${encodeURIComponent(token)}`, { data: change });
  expect(response.ok()).toBe(true);
}

async function backendState(request: APIRequestContext, token: string) {
  const response = await request.get(`${BACKEND}/__state/${encodeURIComponent(token)}`);
  return (await response.json()) as {
    boardRequests: number;
    streamOpens: number;
    streamRefusals: number;
    openStreams: number;
  };
}

/**
 * Breaks the stream and waits until the browser has noticed: it tries to come back
 * and is refused. Only then does the test move the clock, so the 10 seconds of
 * stream gap are counted from the moment the stream really went.
 */
async function breakStream(request: APIRequestContext, token: string, also: Record<string, unknown> = {}) {
  const before = (await backendState(request, token)).streamRefusals;
  await control(request, token, { streamDown: true, drop: true, ...also });
  await expect.poll(async () => (await backendState(request, token)).streamRefusals, { timeout: 15_000 }).toBeGreaterThan(before);
}

async function openLiveBoard(
  page: Page,
  request: APIRequestContext,
  token: string,
  options: { fakeClock?: boolean } = {},
) {
  await signIn(page.context(), 'http://localhost:3000', 'wall', token);
  if (options.fakeClock) await page.clock.install();
  await page.goto('/screen');
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  // The page is hydrated and listening once its stream has reached the back end:
  // only then do the tests move the clock.
  await expect.poll(async () => (await backendState(request, token)).streamOpens, { timeout: 15_000 }).toBeGreaterThan(0);
}

const tiles = (page: Page) => page.locator('[data-el="WALL-TILE"]');
// Next adds its own empty route announcer (role alert); the wall's banner is the only other one.
const alert = (page: Page) => page.locator('[data-el="WALL-OFFLINE-BANNER"]');
const liveRegions = (page: Page) => page.locator('[aria-live]:not(#__next-route-announcer__), [role="status"], [role="alert"]:not(#__next-route-announcer__)');

async function expectCurrent(page: Page) {
  await expect(alert(page)).toHaveCount(0);
  await expect(tiles(page).first()).toHaveAttribute('data-status', 'accepting');
  await expect(page.getByText('Last known', { exact: true })).toHaveCount(0);
}

async function expectLastKnown(page: Page) {
  await expect(alert(page)).toHaveCount(1);
  await expect(alert(page)).toHaveAttribute('role', 'alert');
  await expect(alert(page)).toContainText('Tool offline since');
  await expect(alert(page)).toContainText('Figures are the last known and may be wrong. Use the whiteboard and phone process.');
  await expect(tiles(page)).toHaveCount(9);
  for (const status of await tiles(page).evaluateAll((nodes) => nodes.map((n) => n.getAttribute('data-status')))) {
    expect(status).toBe('last-known');
  }
  // The figure is still there, labelled as old, never blank.
  await expect(tiles(page).first().locator('[data-el="WALL-TILE-NUMBER"]')).toHaveText('4');
  await expect(tiles(page).first()).toContainText('Do not rely on this. Phone to confirm.');
}

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

test('refreshes by itself when the back end says something changed, with no reload and nothing announced', async ({ page, request }) => {
  const token = tokenFor('refresh');
  await openLiveBoard(page, request, token);
  await expectCurrent(page);
  await expect(tiles(page).first().locator('[data-el="WALL-TILE-NUMBER"]')).toHaveText('4');
  await expect.poll(async () => (await backendState(request, token)).openStreams).toBe(1);

  await control(request, token, { ucrWestFree: 7, emit: true });

  await expect(tiles(page).first().locator('[data-el="WALL-TILE-NUMBER"]')).toHaveText('7');
  await expectCurrent(page);
  await expect(liveRegions(page)).toHaveCount(0);
});

test('closes the back end stream when the page goes away', async ({ page, request }) => {
  const token = tokenFor('close');
  await openLiveBoard(page, request, token);
  await expect.poll(async () => (await backendState(request, token)).openStreams).toBe(1);

  await page.goto('about:blank');

  await expect.poll(async () => (await backendState(request, token)).openStreams, { timeout: 15_000 }).toBe(0);
});

test('shows Last known when the board cannot be refreshed and the stream is gone, then recovers on its own', async ({
  page,
  request,
}) => {
  const token = tokenFor('offline');
  await openLiveBoard(page, request, token, { fakeClock: true });
  await expectCurrent(page);

  await breakStream(request, token, { mode: 'down' });
  await page.clock.fastForward(65_000);

  await expectLastKnown(page);

  await control(request, token, { mode: 'ok', streamDown: false });
  await page.clock.fastForward(65_000);

  await expectCurrent(page);
});

test('says in words that live updates are paused, and shows no alert, while the stream is down but the board still refreshes', async ({
  page,
  request,
}) => {
  const token = tokenFor('reconnecting');
  await openLiveBoard(page, request, token, { fakeClock: true });
  await expectCurrent(page);

  await breakStream(request, token);
  await page.clock.fastForward(15_000);

  await expect(page.locator('[data-el="WALL-STREAM-NOTE"]')).toHaveText('Live updates paused. This board refreshes every minute.');
  await expect(alert(page)).toHaveCount(0);
  await expect(tiles(page).first()).toHaveAttribute('data-status', 'accepting');

  await control(request, token, { streamDown: false });
  await expect(page.locator('[data-el="WALL-STREAM-NOTE"]')).toHaveCount(0, { timeout: 20_000 });
});

test('an answer it cannot read falls back to Last known with the old figures, never to a blank or wrong tile', async ({
  page,
  request,
}) => {
  const token = tokenFor('malformed');
  await openLiveBoard(page, request, token);
  await expectCurrent(page);

  await control(request, token, { mode: 'malformed', emit: true });

  await expectLastKnown(page);
  await expect(page.locator('body')).not.toContainText('busy');
});

test('a board that the back end keeps serving but which is already old is Last known at the first paint', async ({
  page,
  request,
}) => {
  const token = tokenFor('stale');
  await control(request, token, { mode: 'stale' });

  await openLiveBoard(page, request, token);

  await expectLastKnown(page);
});

test('goes to /screen/pair when the back end stops knowing this screen', async ({ page, request }) => {
  const token = tokenFor('unpaired');
  await openLiveBoard(page, request, token, { fakeClock: true });
  await expectCurrent(page);
  // A fresh session whose token the back end refuses: the next refetch is a 401.
  await signIn(page.context(), 'http://localhost:3000', 'wall', 'a-token-the-back-end-no-longer-knows');

  await page.clock.fastForward(65_000);

  // The pairing page is W08's: until it exists the address is a 404, but the screen has gone there.
  await expect(page).toHaveURL(/\/screen\/pair$/, { timeout: 20_000 });
});

test('the BFF stream takes no tenant from the address, a query string or a header', async ({ page, request }) => {
  const token = tokenFor('tenant');
  await openLiveBoard(page, request, token);
  const cookies = await page.context().cookies();
  const header = cookies.map((c) => `${c.name}=${c.value}`).join('; ');

  const response = await request.get('http://localhost:3000/api/bff/events?tenant=other&scope=network', {
    headers: { Cookie: header, 'X-Tenant-Id': 'other', 'X-Scope': 'network' },
    timeout: 3_000,
    failOnStatusCode: false,
  }).catch(() => null);

  // The stream is open (the call times out reading it) or answers 200: either way it is this session's.
  if (response !== null) expect(response.status()).toBe(200);
  const state = await backendState(request, token);
  expect(state.streamOpens).toBeGreaterThanOrEqual(2);
});

for (const size of SIZES) {
  test.describe(`live, reconnecting and Last known at ${size.width} by ${size.height}`, () => {
    test.use({ viewport: { width: size.width, height: size.height } });

    test('each state passes axe with colour contrast, has no horizontal scroll, and is photographed', async ({ page, request }) => {
      const token = tokenFor(`shots-${size.name}`);
      await openLiveBoard(page, request, token, { fakeClock: true });

      // Live.
      await expectCurrent(page);
      await noHorizontalScroll(page);
      await checkAxe(page);
      await page.screenshot({ path: resolve(SHOTS, `live-${size.name}.png`), fullPage: true });

      // Reconnecting: the stream is down, the board still refreshes.
      await breakStream(request, token);
      await page.clock.fastForward(15_000);
      await expect(page.locator('[data-el="WALL-STREAM-NOTE"]')).toBeVisible();
      await noHorizontalScroll(page);
      await checkAxe(page);
      await page.screenshot({ path: resolve(SHOTS, `reconnecting-${size.name}.png`), fullPage: true });

      // Last known: nothing can be refreshed.
      await control(request, token, { mode: 'down' });
      await page.clock.fastForward(65_000);
      await expectLastKnown(page);
      await noHorizontalScroll(page);
      await checkAxe(page);
      await page.screenshot({ path: resolve(SHOTS, `last-known-${size.name}.png`), fullPage: true });
    });
  });
}

test('keeps the same information when the user asks for reduced motion', async ({ page, request }) => {
  const token = tokenFor('reduced');
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await openLiveBoard(page, request, token, { fakeClock: true });
  await breakStream(request, token, { mode: 'down' });

  await page.clock.fastForward(65_000);

  await expectLastKnown(page);
});
