import { describe, expect, it } from 'vitest';
import { ANALYTICS_OVERVIEW } from '@/test/fixtures/analytics';
import { AnalyticsParseError, parseAnalyticsOverview } from './parse';

describe('parseAnalyticsOverview', () => {
  it('reads the overview the back end sends', () => {
    expect(parseAnalyticsOverview(structuredClone(ANALYTICS_OVERVIEW))).toEqual(ANALYTICS_OVERVIEW);
  });

  it('refuses a shape it does not know, never a partly filled page', () => {
    const bad = [
      null,
      {},
      { ...ANALYTICS_OVERVIEW, services: 'x' },
      { ...ANALYTICS_OVERVIEW, counts: { accepting: 1 } },
      { ...ANALYTICS_OVERVIEW, services: [{ ...ANALYTICS_OVERVIEW.services[0], status: 'free' }] },
      { ...ANALYTICS_OVERVIEW, services: [{ ...ANALYTICS_OVERVIEW.services[0], districts: [3] }] },
      { ...ANALYTICS_OVERVIEW, underPressure: undefined },
    ];
    for (const item of bad) expect(() => parseAnalyticsOverview(item)).toThrow(AnalyticsParseError);
  });

  it('keeps only the fields the page knows: nothing else is passed on', () => {
    const withExtra = { ...ANALYTICS_OVERVIEW, services: [{ ...ANALYTICS_OVERVIEW.services[0], caseId: 'c1', postcode: 'BH1 1AA' }] };
    const parsed = parseAnalyticsOverview(withExtra);
    expect(JSON.stringify(parsed)).not.toContain('postcode');
    expect(JSON.stringify(parsed)).not.toContain('caseId');
  });
});
