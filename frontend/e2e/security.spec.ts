import { expect, test } from '@playwright/test';
import { TOKEN_ORG_A } from './support/tokens';
import { signIn } from './support/session';

// The policy as a browser sees it (S01): the screen answers with the content security policy,
// every request it makes goes to its own origin, and the browser reports no policy violation.
// Written in the build wave and not run there; the verification run executes it (pnpm e2e).

const BASE_URL = 'http://localhost:3000';

test('the screen loads under the policy, with same-origin requests only and no violation', async ({
  page,
}) => {
  const requested: string[] = [];
  const violations: string[] = [];
  page.on('request', (request) => requested.push(request.url()));
  page.on('console', (message) => {
    if (/content security policy|violates the following/i.test(message.text())) {
      violations.push(message.text());
    }
  });

  await signIn(page.context(), BASE_URL, 'wall', TOKEN_ORG_A);
  const response = await page.goto('/screen');

  const policy = response?.headers()['content-security-policy'] ?? '';
  expect(policy).toContain("script-src 'self' 'nonce-");
  expect(policy).toContain("frame-ancestors 'none'");
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

  const host = new URL(BASE_URL).host;
  expect(requested.filter((url) => new URL(url).host !== host)).toEqual([]);
  expect(violations).toEqual([]);
});
