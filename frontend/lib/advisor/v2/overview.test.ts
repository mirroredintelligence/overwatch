import { describe, expect, it } from 'vitest';
import { areaCards, areaFromQuery, areaHref, attentionShown, districtCards, districtFromQuery, districtHref, groupFromQuery, groupHref, groupsOfRows, locationCards, parseAreas, parseOverview, statusHref, statusesFromQuery, V2_BROWSE_NOTE } from './overview';

// Advisor v2: the capacity overview (DEC-1366). The counts link to filtered lists; the Needs attention lists are
// the shift lead's rules; a stale figure is never spare capacity and is never shown as a number.

const BODY = {
  generatedAt: '2026-11-10T14:00:00Z',
  counts: { accepting: 3, limited: 2, notAccepting: 1, overCapacity: 1, notUpdated: 2 },
  attentionShown: 3,
  underPressure: [
    { serviceId: 'a', name: 'A', status: 'over-capacity', reason: '2 over normal capacity', usedPercent: 120 },
    { serviceId: 'b', name: 'B', status: 'limited', reason: 'Figure is old. Confirm before redirecting demand.', usedPercent: null },
  ],
  underutilised: [{ serviceId: 'c', name: 'C', usedPercent: 20, spare: 8, unitLabel: 'beds free' }],
  services: [
    {
      serviceId: 'a',
      name: 'A',
      category: 'inpatient-beds',
      status: 'accepting',
      effectiveAvailable: 4,
      overBy: null,
      unitLabel: 'beds free',
      reportedAt: '2026-11-10T13:50:00Z',
      figureUnavailable: false,
      lastFigure: 4,
    },
  ],
};

describe('parseOverview', () => {
  it('reads the counts, the two lists and the rows', () => {
    const view = parseOverview(BODY);
    expect(view?.counts).toEqual({ accepting: 3, limited: 2, 'not-accepting': 1, 'over-capacity': 1, 'not-updated': 2 });
    expect(view?.underPressure).toHaveLength(2);
    expect(view?.underutilised[0]).toMatchObject({ serviceId: 'c', spare: 8 });
    expect(view?.services).toHaveLength(1);
  });

  it('is null when the answer is not shaped like an overview', () => {
    expect(parseOverview(null)).toBeNull();
    expect(parseOverview({ ...BODY, counts: undefined })).toBeNull();
  });

  it('shows no percentage for a stale figure under pressure', () => {
    expect(parseOverview(BODY)?.underPressure[1]?.usedPercent).toBeNull();
  });

  it('drops a row it cannot read and reads an unknown status as not updated', () => {
    const view = parseOverview({
      ...BODY,
      services: [{ ...BODY.services[0], serviceId: 1 }, { ...BODY.services[0], status: 'wide-open' }],
    });
    expect(view?.services).toHaveLength(1);
    expect(view?.services[0]?.status).toBe('not-updated');
    expect(view?.services[0]?.figureUnavailable).toBe(true);
  });
});

describe('statusHref', () => {
  it('links a count to the filtered list of v2, not the v1 list', () => {
    expect(statusHref('limited')).toBe('/advisor/v2/services?status=limited');
  });
});

describe('attentionShown', () => {
  it('shows the first few and counts the rest', () => {
    expect(attentionShown([1, 2, 3, 4, 5], 3)).toEqual({ shown: [1, 2, 3], more: 2 });
    expect(attentionShown([1], 3)).toEqual({ shown: [1], more: 0 });
  });
});

describe('V2_BROWSE_NOTE', () => {
  it('says plainly that nothing is stored', () => {
    expect(V2_BROWSE_NOTE).toMatch(/no case/i);
    expect(V2_BROWSE_NOTE).toMatch(/nothing is stored/i);
  });
});

describe('the group and state queries', () => {
  it('links a group to its list and reads it back only when it is shaped like a category', () => {
    expect(groupHref('inpatient-beds')).toBe('/advisor/v2/services?group=inpatient-beds');
    expect(groupFromQuery('inpatient-beds')).toBe('inpatient-beds');
    expect(groupFromQuery(['urgent-community-response', 'x'])).toBe('urgent-community-response');
    expect(groupFromQuery('<script>')).toBeNull();
    expect(groupFromQuery(undefined)).toBeNull();
  });

  it('counts the services of each group, by the group code', () => {
    const rows = parseOverview(BODY)!.services;
    expect(groupsOfRows([...rows, ...rows])).toEqual([{ category: 'inpatient-beds', count: 2 }]);
  });

  it('reads only the five counted states from the address', () => {
    expect(statusesFromQuery('limited,bogus,not-updated')).toEqual(['limited', 'not-updated']);
  });
});

describe('districts', () => {
  const rows = (...specs: [string, string, string[]][]) =>
    parseOverview({
      ...BODY,
      services: specs.map(([id, status, districts]) => ({ ...BODY.services[0], serviceId: id, name: id, status, districts })),
    })!.services;

  it('reads the districts of a row, dropping anything not shaped like a postcode district', () => {
    expect(rows(['a', 'accepting', ['DT4', 'nope', 'BH21']])[0]?.districts).toEqual(['DT4', 'BH21']);
  });

  it('makes one card per district with its services counted by state, and counts a service in each of its districts', () => {
    const cards = districtCards(rows(['a', 'accepting', ['DT4', 'DT1']], ['b', 'limited', ['DT4']], ['c', 'accepting', []]));
    expect(cards.map((card) => [card.district, card.count])).toEqual([['DT1', 1], ['DT4', 2], [null, 1]]);
    expect(cards[1]?.tally).toMatchObject({ accepting: 1, limited: 1, 'not-accepting': 0 });
  });

  it('links a district to its list, and reads it back only when it is shaped like one', () => {
    expect(districtHref('DT4')).toBe('/advisor/v2/services?district=DT4');
    expect(districtHref(null)).toBe('/advisor/v2/services?district=none');
    expect(districtFromQuery('DT4')).toBe('DT4');
    expect(districtFromQuery('none')).toBe('none');
    expect(districtFromQuery('x"><')).toBeNull();
  });
});

// Named areas (DEC-1375): the names arrive from the back end; these are invented.
const AREAS = [
  { id: 'area-one', name: 'Area One', places: 'Alpha · Beta' },
  { id: 'area-two', name: 'Area Two', places: 'Gamma' },
  { id: 'network', name: 'Network-wide', places: 'Services working across areas' },
];
const row = (serviceId: string, status: string, area: string | null, districts: string[] = []) => ({
  serviceId,
  name: serviceId.toUpperCase(),
  category: 'inpatient-beds',
  status,
  effectiveAvailable: 1,
  overBy: null,
  unitLabel: 'beds free',
  reportedAt: '2026-11-10T13:50:00Z',
  figureUnavailable: false,
  lastFigure: 1,
  districts,
  area,
});
const WITH_AREAS = {
  ...BODY,
  areas: AREAS,
  services: [row('a', 'accepting', 'area-one', ['DT4']), row('b', 'limited', 'area-one', ['DT4', 'DT1']), row('c', 'accepting', 'network', ['DT1', 'BH1']), row('d', 'not-updated', null), row('e', 'over-capacity', 'area-two', ['BH7'])],
};

describe('parseAreas', () => {
  it('reads the areas in the order given', () => {
    expect(parseAreas(AREAS)).toEqual(AREAS);
    expect(parseOverview(WITH_AREAS)?.areas).toEqual(AREAS);
  });

  it('reads no list, or a list that is not one, as no areas', () => {
    for (const value of [undefined, null, 'x', {}, 4]) expect(parseAreas(value)).toEqual([]);
    expect(parseOverview({ ...BODY })?.areas).toEqual([]);
  });

  it('drops an entry that is not shaped like an area, and a repeated id', () => {
    const parsed = parseAreas([
      { id: 'Bad Id', name: 'x', places: '' },
      { id: 'a-1', name: '', places: '' },
      { id: 'a-2', name: 'Two', places: 'y'.repeat(201) },
      { id: 'a-3', name: 'Three' },
      { id: 'a-3', name: 'Again', places: '' },
      7,
      { id: 'a-4', name: 'Four', places: 'A · B' },
    ]);
    expect(parsed).toEqual([
      { id: 'a-3', name: 'Three', places: '' },
      { id: 'a-4', name: 'Four', places: 'A · B' },
    ]);
  });

  it('reads a service whose area is not in the list as not placed', () => {
    const view = parseOverview({ ...WITH_AREAS, services: [row('a', 'accepting', 'elsewhere'), row('b', 'accepting', 'area-one')] });
    expect(view?.services.map((service) => service.area)).toEqual([null, 'area-one']);
  });
});

describe('areaCards', () => {
  const view = parseOverview(WITH_AREAS)!;

  it('makes one card per area in the order given and Not placed last, naming each area from the list', () => {
    const cards = areaCards(view.services, view.areas);
    expect(cards.map((card) => card.name)).toEqual(['Area One', 'Area Two', 'Network-wide', 'Not placed']);
    expect(cards.map((card) => card.places)).toEqual(['Alpha · Beta', 'Gamma', 'Services working across areas', 'No area recorded']);
    expect(cards[0]?.tally).toMatchObject({ accepting: 1, limited: 1 });
  });

  it('counts each service once, so the cards add up to every service', () => {
    const cards = areaCards(view.services, view.areas);
    expect(cards.reduce((sum, card) => sum + card.count, 0)).toBe(view.services.length);
    expect(cards.map((card) => card.count)).toEqual([2, 1, 1, 1]);
  });

  it('keeps an area with no service and has no Not placed card when every service has an area', () => {
    const cards = areaCards(view.services.filter((service) => service.area === 'area-one'), view.areas);
    expect(cards.map((card) => [card.name, card.count])).toEqual([['Area One', 2], ['Area Two', 0], ['Network-wide', 0]]);
  });
});

describe('areaHref and areaFromQuery', () => {
  it('links an area to its list, and `none` for not placed', () => {
    expect(areaHref('area-one')).toBe('/advisor/v2/services?area=area-one');
    expect(areaHref(null)).toBe('/advisor/v2/services?area=none');
  });

  it('reads back only an id shaped like one or `none`', () => {
    expect(areaFromQuery('area-one')).toBe('area-one');
    expect(areaFromQuery(['none', 'x'])).toBe('none');
    for (const bad of [undefined, '', 'Area One', 'a/b', '../x', 'x'.repeat(41), '<script>']) expect(areaFromQuery(bad)).toBeNull();
  });

  it('reads back only an area the organisation has, when it is given the areas', () => {
    expect(areaFromQuery('area-two', AREAS)).toBe('area-two');
    expect(areaFromQuery('none', AREAS)).toBe('none');
    expect(areaFromQuery('another', AREAS)).toBeNull();
  });
});

describe('locationCards', () => {
  it('is the areas when there are areas, each linking to its area list', () => {
    const cards = locationCards(parseOverview(WITH_AREAS)!);
    expect(cards.map((card) => card.name)).toEqual(['Area One', 'Area Two', 'Network-wide', 'Not placed']);
    expect(cards.map((card) => card.href)).toEqual(['/advisor/v2/services?area=area-one', '/advisor/v2/services?area=area-two', '/advisor/v2/services?area=network', '/advisor/v2/services?area=none']);
  });

  it('is the postcode districts, as before, when there are no areas', () => {
    const cards = locationCards(parseOverview({ ...WITH_AREAS, areas: [] })!);
    expect(cards.map((card) => card.name)).toEqual(['BH1', 'BH7', 'DT1', 'DT4', 'Not placed']);
    expect(cards[3]?.href).toBe('/advisor/v2/services?district=DT4');
    expect(cards[3]?.sub).toBe('Postcode district');
  });
});
