import { describe, expect, it } from 'vitest';
import { summaryFromParameters, timeBack, weekEndingDefault, weekStartFor, type Figure } from './weekSummary';

const shown = (value: number): Figure => ({ value, suppressed: false });
const withheld: Figure = { value: null, suppressed: true };

function parameters(overrides: Record<string, unknown> = {}) {
  const figure = (name: string, value: unknown) => ({
    name,
    part: value === 'suppressed'
      ? [{ name: 'suppressed', valueBoolean: true }]
      : [{ name: 'suppressed', valueBoolean: false }, { name: 'value', valueInteger: value }],
  });
  return {
    resourceType: 'Parameters',
    parameter: [
      { name: 'weekStart', valueDate: '2026-10-19' },
      figure('referrals', 640),
      figure('bestFitUnavailablePct', 18),
      figure('onTimePct', 92),
      figure('medianMinutesToConfirmed', 4),
      {
        name: 'updatesByChannel',
        part: [
          { name: 'text', part: [{ name: 'suppressed', valueBoolean: false }, { name: 'value', valueInteger: 250 }] },
          { name: 'app', part: [{ name: 'suppressed', valueBoolean: false }, { name: 'value', valueInteger: 120 }] },
          { name: 'email', part: [{ name: 'suppressed', valueBoolean: false }, { name: 'value', valueInteger: 42 }] },
        ],
      },
      ...Object.entries(overrides).map(([name, value]) => figure(name, value)),
    ],
  };
}

describe('weekEndingDefault and weekStartFor', () => {
  it('ends the last complete Monday-to-Sunday week before today', () => {
    // Friday 30 October 2026: the last complete week ended on Sunday 25 October.
    expect(weekEndingDefault(new Date('2026-10-30T10:00:00Z'))).toBe('2026-10-25');
  });

  it('starts that week on the Monday six days before its Sunday', () => {
    expect(weekStartFor('2026-10-25')).toBe('2026-10-19');
  });

  it('refuses an ending that is not a Sunday', () => {
    expect(() => weekStartFor('2026-10-23')).toThrow();
  });
});

describe('summaryFromParameters', () => {
  it('maps the figures and sums the channels when none is withheld', () => {
    const summary = summaryFromParameters(parameters(), null);
    expect(summary.from).toBe('2026-10-19');
    expect(summary.to).toBe('2026-10-25');
    expect(summary.referrals).toEqual(shown(640));
    expect(summary.updates).toEqual(shown(412));
    expect(summary.minutesPerCall).toBeNull();
  });

  it('withholds the total when one channel is under ten', () => {
    const body = parameters();
    (body.parameter as { name: string; part?: unknown[] }[])[5] = {
      name: 'updatesByChannel',
      part: [
        { name: 'text', part: [{ name: 'suppressed', valueBoolean: false }, { name: 'value', valueInteger: 250 }] },
        { name: 'email', part: [{ name: 'suppressed', valueBoolean: true }] },
      ],
    };
    expect(summaryFromParameters(body, null).updates).toEqual(withheld);
  });

  it('refuses a body with no figure it needs', () => {
    expect(() => summaryFromParameters({ resourceType: 'Parameters', parameter: [] }, null)).toThrow();
  });
});

describe('timeBack', () => {
  it('keeps [x] and says the baseline is not measured while the minutes are unset', () => {
    expect(timeBack(shown(412), null)).toEqual({
      sentence: '412 updates by text, app or email. Each replaces about one phone call of [x] minutes.',
      estimate: 'Estimate until we measure the baseline.',
    });
  });

  it('shows the sum behind the estimate when the minutes are set', () => {
    expect(timeBack(shown(412), 4).estimate).toBe('about 1,648 minutes (412 × 4)');
  });

  it('shows no estimate for a withheld count', () => {
    expect(timeBack(withheld, 4).estimate).toBeNull();
  });
});
