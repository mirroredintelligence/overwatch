import { describe, expect, it } from 'vitest';
import { biggestDrop, type FunnelStep } from './funnel';

const STEPS: FunnelStep[] = [
  { name: 'Link sent', pct: 100, count: 412, suppressed: false },
  { name: 'Link opened', pct: 95, count: 391, suppressed: false, exitElementId: 'L-CODE-INPUT', medianSeconds: 42 },
  { name: 'Small step', pct: null, count: null, suppressed: true },
  { name: 'Code verified', pct: 84, count: 346, suppressed: false },
  { name: 'Reply sent', pct: 80, count: 330, suppressed: false },
];

describe('biggestDrop', () => {
  it('finds "Link opened to Code verified: 11 points" in the sample funnel, and skips a suppressed step', () => {
    const drop = biggestDrop(STEPS);

    expect(drop).not.toBeNull();
    expect(drop?.from).toBe('Link opened');
    expect(drop?.to).toBe('Code verified');
    expect(drop?.points).toBe(11);
    // The exit and the median time belong to the step the people left from.
    expect(drop?.exitElementId).toBe('L-CODE-INPUT');
    expect(drop?.medianSeconds).toBe(42);
  });

  it('never names a suppressed step as either side of a drop', () => {
    const drop = biggestDrop(STEPS);

    expect([drop?.from, drop?.to]).not.toContain('Small step');
  });

  it('answers null when there is no pair of shown steps to compare', () => {
    expect(biggestDrop([{ name: 'Only', pct: 100, count: 12, suppressed: false }])).toBeNull();
  });
});
