import { describe, expect, it } from 'vitest';
import { attentionShown, districtCards, districtFromQuery, districtHref, groupFromQuery, groupHref, groupsOfRows, parseOverview, statusHref, statusesFromQuery, V2_BROWSE_NOTE } from './overview';

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
