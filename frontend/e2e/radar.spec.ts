import AxeBuilder from '@axe-core/playwright';
import { expect, type Page, test } from '@playwright/test';
import { SITE_URL } from './support/env';
import { signIn } from './support/session';
import { TOKEN_ORG_A } from './support/tokens';

// The radar, the map and the coverage screens in a real browser (RadarWeb, RadarPhone, MapWeb, MapPhone).
// The advisor's cases are the stand-in's own radar cases (e2e/support/radar.ts): `radar-1` has a placed
// postcode and four options, `radar-nf` has a postcode that is not found until one is saved. The coverage
// routes are not served by the real back end yet, so those two screens run against the stand-in's contract.

const PHONE = { width: 390, height: 844 };
// A page's first visit compiles it in the dev server, while the other workers do the same: give it time.
const FIRST = { timeout: 30_000 };

async function noSidewaysScroll(page: Page) {
  const { scroll, client } = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    client: document.documentElement.clientWidth,
  }));
  expect(scroll).toBeLessThanOrEqual(client);
}

async function axe(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  expect(results.violations).toEqual([]);
}

test.describe('the advisor’s radar (RadarWeb 1, 2, 6)', () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page.context(), SITE_URL, 'advisor', TOKEN_ORG_A);
  });

  test('who covers this area: the summary, the layers and the way on', async ({ page }) => {
    await page.goto('/advisor/case/radar-1/radar');
    await expect(page.getByRole('heading', { name: 'Who covers DT4' })).toBeVisible(FIRST);
    await expect(page.getByText('This patient is covered by 3 services. Their areas overlap here, so compare them.')).toBeVisible();
    const areas = page.locator('[data-el="RADAR-PICTURE"] circle[stroke-dasharray]');
    await expect(areas).toHaveCount(3);
    await expect(page.locator('[data-el="RADAR-OVERLAP"]')).toHaveCount(3);

    await page.locator('[data-el="RADAR-LAYER-VISITING"]').click();
    await expect(areas).toHaveCount(1);
    await expect(page.getByRole('button', { name: 'Traffic: not available yet' })).toBeDisabled();
    await axe(page);

    await page.locator('[data-el="RADAR-COMPARE-BTN"]').click();
    await expect(page).toHaveURL(/\/advisor\/case\/radar-1\/compare$/);
  });

  test('compare: three services side by side, in shadow mode, not ranked', async ({ page }) => {
    await page.goto('/advisor/case/radar-1/compare');
    await expect(page.getByRole('heading', { name: 'Compare for this patient' })).toBeVisible(FIRST);
    await expect(page.locator('[data-el="RADAR-SHADOW"]')).toContainText('It does not pick one.');
    const table = page.getByRole('table');
    await expect(table.getByRole('columnheader')).toHaveText(['Measure', 'UCR West', 'UCR East', 'Hospital at home']);
    await expect(table.locator('[data-row="free"]')).toContainText('+2 over');
    await expect(table.locator('[data-row="round"]')).toContainText('Not available');
    await expect(page.getByRole('group', { name: 'Request UCR East' }).getByRole('button', { name: 'Request booking' })).toBeVisible();
    await page.locator('[data-el="RADAR-WHY-BTN"]').click();
    await expect(page.getByRole('list', { name: 'Why these numbers' })).toBeVisible();
    await axe(page);
  });

  test('three ways: the answer to can the patient travel changes the order, and nothing is hidden', async ({ page }) => {
    await page.goto('/advisor/case/radar-1/ways');
    await expect(page.getByRole('heading', { name: 'Meeting this need' })).toBeVisible(FIRST);
    const lanes = page.getByRole('heading', { level: 3 });
    await expect(lanes).toHaveText(['Comes to the patient', 'Remote', 'Goes to a place']);
    await page.locator('[data-el="RADAR-TRAVEL-YES"]').click();
    await expect(lanes).toHaveText(['Goes to a place', 'Comes to the patient', 'Remote']);
    await expect(page.locator('[data-el="RADAR-WAY-ROW"]')).toHaveCount(4);
    await page.getByRole('button', { name: '1 service not suitable, and why' }).click();
    await expect(page.getByText('Urgent treatment centre: Open until 20:00, not suited to this need')).toBeVisible();
    await axe(page);
  });

  test('on a phone none of the three views scrolls sideways, and each passes axe', async ({ page }) => {
    await page.setViewportSize(PHONE);
    for (const [path, heading] of [
      ['radar', 'Who covers DT4'],
      ['compare', 'Compare for this patient'],
      ['ways', 'Meeting this need'],
    ] as const) {
      await page.goto(`/advisor/case/radar-1/${path}`);
      await expect(page.getByRole('heading', { name: heading })).toBeVisible(FIRST);
      await noSidewaysScroll(page);
      await axe(page);
    }
  });

  test('on a phone the compare table is a stack: each figure names its service', async ({ page }) => {
    await page.setViewportSize(PHONE);
    await page.goto('/advisor/case/radar-1/compare');
    const status = page.locator('[data-row="status"] td').first();
    await expect(status).toBeVisible();
    expect(await status.evaluate((cell) => getComputedStyle(cell, '::before').content)).toContain('UCR West');
    await expect(page.getByRole('columnheader', { name: 'UCR West' })).toBeAttached();
  });
});

test.describe('the map, closed against MapWeb and MapPhone', () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page.context(), SITE_URL, 'advisor', TOKEN_ORG_A);
  });

  test('a pin shows its card with the criteria version and the dotted route; a visiting area is a button too', async ({ page }) => {
    await page.goto('/advisor/case/radar-1/map');
    await expect(page.getByRole('heading', { name: 'Options near DT4' })).toBeVisible(FIRST);
    await expect(page.locator('[data-el="ADV-MAP-COUNT"]')).toHaveText('4 services shown');
    await expect(page.locator('[data-el="ADV-MAP-ROUTE"]')).toHaveCount(0);

    await page.getByRole('button', { name: 'Community hospital · Ward B' }).click();
    const card = page.locator('[data-el="ADV-MAP-CARD"]');
    await expect(card).toContainText('Criteria version 3');
    await expect(card).toContainText('Patient to Community hospital · Ward B by road 35 to 50 min');
    await expect(page.locator('[data-el="ADV-MAP-ROUTE"]')).toHaveCount(1);

    await page.getByRole('button', { name: 'Hospital at home (visits)' }).click();
    await expect(card).toContainText('Hospital at home');
    await expect(page.locator('[data-el="ADV-MAP-ROUTE"]')).toHaveCount(0);
    await axe(page);

    await page.locator('[data-el="ADV-MAP-RADAR-BTN"]').click();
    await expect(page).toHaveURL(/\/advisor\/case\/radar-1\/radar$/);
  });

  test('on a phone the map does not scroll sideways', async ({ page }) => {
    await page.setViewportSize(PHONE);
    await page.goto('/advisor/case/radar-1/map');
    await expect(page.getByRole('heading', { name: 'Options near DT4' })).toBeVisible(FIRST);
    await page.getByRole('button', { name: 'Community hospital · Ward B' }).click();
    await noSidewaysScroll(page);
    await axe(page);
  });

  test('a postcode that is not found can be typed again in place, and the map is drawn', async ({ page }) => {
    await page.goto('/advisor/case/radar-nf/map');
    await expect(page.getByRole('heading', { name: 'We could not find that postcode' })).toBeVisible(FIRST);
    await expect(page.getByRole('link', { name: 'Phone a service you know has space' })).toBeVisible();
    await axe(page);

    await page.locator('[data-el="ADV-POSTCODE-FIX"]').fill('DT4 8X');
    await page.locator('[data-el="ADV-POSTCODE-SEARCH-BTN"]').click();
    await expect(page.locator('p[role="alert"]')).toContainText('Enter a full postcode, like DT4 8XX.');

    await page.locator('[data-el="ADV-POSTCODE-FIX"]').fill('dt4 8xx');
    await page.locator('[data-el="ADV-POSTCODE-SEARCH-BTN"]').click();
    await expect(page.getByRole('heading', { name: 'Options near DT4' })).toBeVisible(FIRST);
  });
});

test.describe('where coverage runs out (RadarWeb 4)', () => {
  for (const role of ['lead', 'exec'] as const) {
    test(`a ${role} sees the districts, the gaps and the referrals from uncovered areas`, async ({ page }) => {
      await signIn(page.context(), SITE_URL, role, TOKEN_ORG_A);
      await page.goto('/planning/coverage');
      await expect(page.getByRole('heading', { name: 'Coverage by time of day' })).toBeVisible(FIRST);
      await expect(page.locator('[data-el="COV-NONE"]')).toHaveText('DT5, DT6');
      await expect(page.locator('[data-el="COV-MANY"]')).toHaveText('DT3, DT4');
      await expect(page.locator('[data-el="COV-REFERRALS"]')).toHaveText('31');

      await page.locator('[data-el="COV-WINDOW-NIGHT"]').click();
      await expect(page.locator('[data-el="COV-NONE"]')).toHaveText('DT1, DT2, DT5, DT6');
      await expect(page.locator('[data-el="COV-REFERRALS"]')).toHaveText('Fewer than 10');
      await axe(page);
    });
  }

  test('an advisor is kept off it', async ({ page }) => {
    await signIn(page.context(), SITE_URL, 'advisor', TOKEN_ORG_A);
    await page.goto('/planning/coverage');
    await expect(page.getByRole('heading', { level: 1, name: 'You do not have access to this page.' })).toBeVisible(FIRST);
  });

  test('on a phone it does not scroll sideways', async ({ page }) => {
    await signIn(page.context(), SITE_URL, 'lead', TOKEN_ORG_A);
    await page.setViewportSize(PHONE);
    await page.goto('/planning/coverage');
    await expect(page.locator('[data-el="COV-TILES"]')).toBeVisible(FIRST);
    await noSidewaysScroll(page);
    await axe(page);
  });
});

// The pages that were built but had no way in are reached by a link a person would use.
test.describe('the way in to the radar and the coverage pages', () => {
  test('the options list links to who covers, the comparison and the three ways', async ({ page }) => {
    await signIn(page.context(), SITE_URL, 'advisor', TOKEN_ORG_A);
    await page.goto('/advisor/case/radar-1/options');
    await expect(page.getByRole('link', { name: 'Who covers this patient' })).toBeVisible(FIRST);
    await expect(page.getByRole('link', { name: 'Compare options side by side' })).toHaveAttribute('href', '/advisor/case/radar-1/compare');
    await expect(page.getByRole('link', { name: 'Three ways to meet the need' })).toHaveAttribute('href', '/advisor/case/radar-1/ways');
    await page.getByRole('link', { name: 'Who covers this patient' }).click();
    await expect(page).toHaveURL(/\/advisor\/case\/radar-1\/radar$/);
    await expect(page.getByRole('heading', { name: 'Who covers DT4' })).toBeVisible(FIRST);
  });

  test('the planning home and its header both lead to where coverage runs out', async ({ page }) => {
    await signIn(page.context(), SITE_URL, 'exec', TOKEN_ORG_A);
    await page.goto('/planning');
    await expect(page.getByRole('link', { name: 'Where coverage runs out' })).toBeVisible(FIRST);
    await page.getByRole('link', { name: 'Where coverage runs out' }).click();
    await expect(page).toHaveURL(/\/planning\/coverage$/);
    await expect(page.getByRole('heading', { name: 'Coverage by time of day' })).toBeVisible(FIRST);
    await expect(page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Coverage by time' })).toHaveAttribute('aria-current', 'page');
  });

  test('the shift lead overview links to where coverage runs out', async ({ page }) => {
    await signIn(page.context(), SITE_URL, 'lead', TOKEN_ORG_A);
    await page.goto('/lead');
    await page.getByRole('link', { name: 'Where coverage runs out' }).click();
    await expect(page).toHaveURL(/\/planning\/coverage$/);
    await expect(page.getByRole('heading', { name: 'Coverage by time of day' })).toBeVisible(FIRST);
  });
});

test.describe('define a coverage area (RadarWeb 5)', () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page.context(), SITE_URL, 'lead', TOKEN_ORG_A);
  });

  test('the lead sees the overlap, changes the districts and saves', async ({ page }) => {
    await page.goto('/lead/coverage/svc-ucr-west');
    await expect(page.getByRole('heading', { name: 'Where does UCR West go?' })).toBeVisible(FIRST);
    await expect(page.locator('[data-el="COV-OVERLAP"]')).toContainText('UCR East also covers DT4.');

    await page.locator('[data-el="COV-DISTRICT-DT4"]').click();
    await expect(page.locator('[data-el="COV-OVERLAP"]')).toHaveCount(0);
    await page.locator('[data-el="COV-DISTRICT-DT5"]').click();
    await page.locator('[data-el="COV-DAY-SAT"]').click();
    await page.locator('[data-el="COV-SAVE-BTN"]').click();
    await expect(page.getByText('The coverage area is saved.')).toBeVisible();
    await axe(page);
  });

  test('a form with nothing chosen says what is missing, in a summary that takes focus', async ({ page }) => {
    await page.goto('/lead/coverage/svc-ucr-west');
    await expect(page.getByRole('heading', { name: 'Where does UCR West go?' })).toBeVisible(FIRST);
    for (const district of ['DT3', 'DT4']) await page.locator(`[data-el="COV-DISTRICT-${district}"]`).click();
    await page.locator('[data-el="COV-SAVE-BTN"]').click();
    await expect(page.locator('[data-el="FORM-ERROR-SUMMARY"]')).toContainText('Choose at least one district.');
    await axe(page);
  });

  test('a service with no coverage area says so', async ({ page }) => {
    await page.goto('/lead/coverage/svc-none');
    await expect(page.locator('p[role="alert"]')).toContainText('The coverage area is not available for this service yet.');
  });

  test('on a phone it does not scroll sideways', async ({ page }) => {
    await page.setViewportSize(PHONE);
    await page.goto('/lead/coverage/svc-ucr-west');
    await expect(page.getByRole('heading', { name: 'Where does UCR West go?' })).toBeVisible(FIRST);
    await noSidewaysScroll(page);
    await axe(page);
  });
});
