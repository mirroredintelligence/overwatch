// The status of a measure against its budget, as a word (W49). A colour never carries it alone.
// A value exactly at the budget is within it.

export type BudgetStatus = 'Within budget' | 'Over budget';

export function budgetStatus(value: number, budget: number): BudgetStatus {
  return value <= budget ? 'Within budget' : 'Over budget';
}
