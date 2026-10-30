import { describe, expect, it } from 'vitest';
import { checkProblem, checkSafetyConcern, PROBLEM_KINDS, REPORT_LIMIT, SAFETY_CATEGORIES } from './report';

describe('checkSafetyConcern', () => {
  it('needs a category and the text', () => {
    const result = checkSafetyConcern({});
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errors).toEqual(expect.arrayContaining(['Choose what it is about.', 'Tell us what happened.']));
  });

  it('takes the five categories the back end holds, and an optional reference', () => {
    expect(SAFETY_CATEGORIES).toEqual(['wrong-service-shown', 'out-of-date-criteria', 'wrong-status-on-board', 'message-went-to-wrong-place', 'something-else']);
    expect(checkSafetyConcern({ category: 'wrong-status-on-board', text: 'Shows full, has a bed' })).toEqual({
      ok: true,
      value: { category: 'wrong-status-on-board', text: 'Shows full, has a bed' },
    });
  });

  it('refuses a text of 281 characters and names the limit', () => {
    const result = checkSafetyConcern({ category: 'something-else', text: 'x'.repeat(REPORT_LIMIT + 1) });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.errors).toContain(`Keep it to ${REPORT_LIMIT} characters`);
  });

  it('refuses a category that is not on the list', () => {
    expect(checkSafetyConcern({ category: 'bad', text: 'x' }).ok).toBe(false);
  });
});

describe('checkProblem', () => {
  it('takes the back end\'s four kinds, and the optional text', () => {
    expect(PROBLEM_KINDS).toEqual(['screen-slow', 'button-does-not-work', 'figure-looks-wrong', 'something-else']);
    expect(checkProblem({ kind: 'button-does-not-work', route: '/case/[ref]' })).toEqual({
      ok: true,
      value: { kind: 'button-does-not-work', route: '/case/[ref]' },
    });
  });

  it('refuses a kind it does not know, and a route that is not a page path', () => {
    expect(checkProblem({ kind: 'button-not-working', route: '/help' }).ok).toBe(false);
    expect(checkProblem({ kind: 'screen-slow', route: 'https://elsewhere.example/x' }).ok).toBe(false);
  });
});
