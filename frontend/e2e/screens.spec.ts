import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { standInToken } from '@/test/fixtures/exchange';
import { signIn } from './support/session';

// Connecting a wall screen in a real browser: the display with nobody signed in, the shift lead's
// page, and the board that follows. The back end is the stand-in of e2e/support (pairing and token
// exchange, R15 and TEN-043); it is not the back end.

const tokenFor = (role: string) =>
  standInToken({ sub: `stf-e2e-${role}`, role, aud: 'diucs-api', exp: Math.floor(Date.now() / 1000) + 3600 });

test('shows a code on a display with no session, in groups of three, and nothing a person could type on it', async ({ page }) => {
  await page.goto('/screen/pair');

  await expect(page.getByRole('heading', { level: 1, name: 'DIUCS capacity wall screen' })).toBeVisible();
  await expect(page.locator('[data-el="WALL-PAIR-CODE"]')).toHaveText(/^\d{3} \d{3}$/);
  await expect(page.getByText('Enter this code in the admin page to connect this screen.')).toBeVisible();
  await expect(page.getByText('Waiting to be connected · code works for 10 minutes')).toBeVisible();
  await expect(page.locator('main button, main input, main a')).toHaveCount(0);
});

test('connects a display from a lead’s page, and the display goes on to the board by itself', async ({ browser, baseURL }) => {
  const display = await browser.newContext({ baseURL });
  const lead = await browser.newContext({ baseURL });
  const wall = await display.newPage();
  await wall.goto('/screen/pair');
  const shown = (await wall.locator('[data-el="WALL-PAIR-CODE"]').textContent()) ?? '';
  expect(shown).toMatch(/^\d{3} \d{3}$/);

  await signIn(lead, new URL(wall.url()).origin, 'lead', tokenFor('lead'));
  const admin = await lead.newPage();
  await admin.goto('/lead/screens/new');
  await admin.getByLabel(/Code shown on the screen/).fill(shown);
  await admin.getByLabel(/Screen name/).fill('Control room');
  await admin.getByLabel(/Where it is/).fill('Ward 4 corridor');
  await admin.getByRole('button', { name: 'Connect screen' }).click();

  await expect(admin.getByRole('heading', { name: 'Screen connected' })).toBeVisible();
  await expect(admin.getByText('Control room is now showing the live board.')).toBeVisible();
  await expect(admin.getByText(/^Online, updated \d\d:\d\d$/)).toBeVisible();

  // The display polls every three seconds.
  await expect(wall).toHaveURL(/\/screen$/, { timeout: 15_000 });
  await expect(wall.getByRole('heading', { level: 1 })).toBeVisible();

  // Neither token reached the page or its storage.
  const everything = await wall.evaluate(() => JSON.stringify([document.documentElement.outerHTML, localStorage, sessionStorage, document.cookie]));
  expect(everything).not.toMatch(/device-token|screen-secret|eyJ[A-Za-z0-9_-]{10,}\./);
  const cookies = await display.cookies();
  expect(cookies.find((c) => c.name === 'diucs_session')).toMatchObject({ httpOnly: true, sameSite: 'Strict' });
  expect(cookies.find((c) => c.name === 'diucs_device')).toMatchObject({ httpOnly: true, sameSite: 'Strict' });
  expect(cookies.find((c) => c.name === 'diucs_pairing')).toBeUndefined();
  await display.close();
  await lead.close();
});

test('says the code is not valid beside the field when it is wrong', async ({ browser, baseURL }) => {
  const lead = await browser.newContext({ baseURL });
  await signIn(lead, baseURL!, 'lead', tokenFor('lead'));
  const admin = await lead.newPage();
  await admin.goto('/lead/screens/new');
  await admin.getByLabel(/Code shown on the screen/).fill('000000');
  await admin.getByLabel(/Screen name/).fill('Control room');
  await admin.getByRole('button', { name: 'Connect screen' }).click();

  await expect(admin.getByText('That code is not valid or has expired. Check the screen for a new code.')).toBeVisible();
  await expect(admin.getByLabel(/Code shown on the screen/)).toBeFocused();
  await lead.close();
});

test('says what is wrong with an empty or short code without asking the back end', async ({ browser, baseURL }) => {
  const lead = await browser.newContext({ baseURL });
  await signIn(lead, baseURL!, 'lead', tokenFor('lead'));
  const admin = await lead.newPage();
  await admin.goto('/lead/screens/new');
  await admin.getByRole('button', { name: 'Connect screen' }).click();
  await expect(admin.getByText('Enter the code shown on the screen')).toBeVisible();
  await expect(admin.getByText('Enter a name for the screen')).toBeVisible();
  await admin.getByLabel(/Code shown on the screen/).fill('48291');
  await admin.getByRole('button', { name: 'Connect screen' }).click();
  await expect(admin.getByText('The code has 6 numbers')).toBeVisible();
  await lead.close();
});

test('keeps every role but the lead out of the lead page', async ({ browser, baseURL }) => {
  const advisor = await browser.newContext({ baseURL });
  await signIn(advisor, baseURL!, 'advisor', tokenFor('advisor'));
  const page = await advisor.newPage();
  const response = await page.goto('/lead/screens/new');
  expect(response?.status()).toBe(403);
  await advisor.close();
});

test('sends a display that already has a wall session to the board, and asks for no code', async ({ browser, baseURL }) => {
  const display = await browser.newContext({ baseURL });
  await signIn(display, baseURL!, 'wall', tokenFor('wall'));
  const page = await display.newPage();
  await page.goto('/screen/pair');
  await expect(page).toHaveURL(/\/screen$/);
  await display.close();
});

test('refuses a pairing request that comes from another site', async ({ request, baseURL }) => {
  const response = await request.post(`${baseURL}/api/bff/screens/pairing`, { headers: { Origin: 'https://evil.example' } });
  expect(response.status()).toBe(403);
});

for (const [name, path] of [
  ['the display’s pairing', '/screen/pair'],
  ['the lead’s form', '/lead/screens/new'],
] as const) {
  test(`has no axe violations on ${name}, with colour contrast`, async ({ browser, baseURL }) => {
    const context = await browser.newContext({ baseURL });
    if (path.startsWith('/lead')) await signIn(context, baseURL!, 'lead', tokenFor('lead'));
    const page = await context.newPage();
    await page.goto(path);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await page.locator('[data-el="WALL-PAIR-CODE"], [data-el="LEAD-SCREEN-CONNECT-BTN"]').first().waitFor();

    const results = await new AxeBuilder({ page }).analyze();

    expect(results.violations).toEqual([]);
    await context.close();
  });
}

test('reads at phone width without sideways scroll', async ({ browser, baseURL }) => {
  const context = await browser.newContext({ baseURL, viewport: { width: 360, height: 740 } });
  await signIn(context, baseURL!, 'lead', tokenFor('lead'));
  const page = await context.newPage();
  for (const path of ['/screen/pair', '/lead/screens/new']) {
    await page.goto(path);
    await page.getByRole('heading', { level: 1 }).waitFor();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  }
  await context.close();
});
