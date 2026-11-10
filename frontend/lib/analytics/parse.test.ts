import { describe, expect, it } from 'vitest';
import { ANALYTICS_AREAS, ANALYTICS_OVERVIEW, ANALYTICS_OVERVIEW_AREAS } from '@/test/fixtures/analytics';
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

describe('the areas (DEC-1375)', () => {
  it('reads the areas in the order given and each service\'s one area', () => {
    const parsed = parseAnalyticsOverview(structuredClone(ANALYTICS_OVERVIEW_AREAS));
    expect(parsed.areas).toEqual(ANALYTICS_AREAS);
    expect(parsed.services.map((service) => service.area)).toEqual(['area-one', 'network', 'area-one', null, 'area-two']);
  });

  it('reads a back end with no area table as no areas and no service placed in one', () => {
    const without: Record<string, unknown> = structuredClone(ANALYTICS_OVERVIEW_AREAS);
    Reflect.deleteProperty(without, 'areas');
    const parsed = parseAnalyticsOverview(without);
    expect(parsed.areas).toEqual([]);
    expect(parsed.services.every((service) => service.area === null)).toBe(true);
  });

  it('drops an area that is not shaped like one and a repeated id, and keeps the rest in order', () => {
    const parsed = parseAnalyticsOverview({
      ...structuredClone(ANALYTICS_OVERVIEW_AREAS),
      areas: [
        { id: 'Area One', name: 'Bad id', places: '' },
        { id: 'one', name: 'One', places: 'x'.repeat(201) },
        { id: 'two', name: '', places: '' },
        { id: 'three', name: 'Three' },
        { id: 'three', name: 'Three again', places: '' },
        { id: 7, name: 'Seven' },
        'x',
        { id: 'four', name: 'Four', places: 'A · B' },
      ],
    });
    expect(parsed.areas).toEqual([
      { id: 'three', name: 'Three', places: '' },
      { id: 'four', name: 'Four', places: 'A · B' },
    ]);
  });

  it('reads a service whose area the list does not hold as not placed, never under a card that is not there', () => {
    const parsed = parseAnalyticsOverview({
      ...structuredClone(ANALYTICS_OVERVIEW_AREAS),
      services: [{ ...ANALYTICS_OVERVIEW_AREAS.services[0], area: 'somewhere-else' }, { ...ANALYTICS_OVERVIEW_AREAS.services[1], area: 4 }],
    });
    expect(parsed.services.map((service) => service.area)).toEqual([null, null]);
  });
});
