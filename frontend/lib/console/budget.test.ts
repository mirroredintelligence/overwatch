import { describe, expect, it } from 'vitest';
import { budgetStatus } from './budget';

// The status is a word, so a colour is never the only signal (W49).
describe('budgetStatus', () => {
  it('is Over budget when the value is above the budget', () => {
    expect(budgetStatus(240, 200)).toBe('Over budget');
  });

  it('is Within budget when the value is under the budget', () => {
    expect(budgetStatus(2.1, 2.5)).toBe('Within budget');
  });

  it('is Within budget when the value is exactly the budget', () => {
    expect(budgetStatus(200, 200)).toBe('Within budget');
  });
});
