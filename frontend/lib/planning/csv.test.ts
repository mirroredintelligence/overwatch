import { describe, expect, it } from 'vitest';
import { toCsv } from './csv';
import type { Planning } from './types';

const PLANNING: Planning = {
  cohort: 'Cohort: age 65+.',
  referrals: 640,
  bestFitUnavailable: { count: 112, pct: 18 },
  wentElsewhere: 62,
  flows: [
    { bestFit: 'Falls team, Weymouth', state: 'full', wentTo: 'Community beds', count: 41, suppressed: false },
    { bestFit: 'Frailty ward', state: 'closed', wentTo: 'Virtual ward', count: null, suppressed: true },
  ],
  grid: [],
  declinedDespite: [{ service: 'Ward "B"', count: 12, suppressed: false }],
};

describe('toCsv', () => {
  it('writes the flows and the declined rows, with a header line each', () => {
    const lines = toCsv(PLANNING).split('\r\n');

    expect(lines[0]).toBe('Section,Best fit,State,Went to,Referrals');
    expect(lines).toContain('Flow,"Falls team, Weymouth",full,Community beds,41');
  });

  it('leaves the count of a suppressed row empty, so no small number is exported', () => {
    expect(toCsv(PLANNING)).toContain('Flow,Frailty ward,closed,Virtual ward,\r\n');
  });

  it('doubles the quotes inside a field', () => {
    expect(toCsv(PLANNING)).toContain('Declined,"Ward ""B""",,,12');
  });
});
