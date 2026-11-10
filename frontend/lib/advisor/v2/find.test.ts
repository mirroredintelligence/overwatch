import { describe, expect, it } from 'vitest';
import { groupsOf, orderServices, parseFind, toOption, type FoundService } from './find';

// Advisor v2: find a service (DEC-1366). Pure. The answer of POST /advisor-v2/find is read into plain data: a
// service that is not shaped like one is dropped, a status the rules do not know is "not updated" (never
// accepting), a late or old figure is never the current capacity, and no list is ordered by status.

function service(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    serviceId: 'svc-a',
    name: 'Alpha',
    category: 'urgent-community-response',
    status: 'accepting',
    effectiveAvailable: 5,
    overBy: null,
    unitLabel: 'referrals',
    dataAgeSeconds: 1200,
    reportedAt: '2026-11-10T13:40:00Z',
    nextDueAt: '2026-11-10T15:40:00Z',
    cadence: 'every-2-hrs',
    overdue: false,
    staleWarning: false,
    figureUnavailable: false,
    lastFigure: 5,
    criteriaVersion: 1,
    fits: ['Covers this postcode'],
    warnings: ['Limited: phone to confirm'],
    phone: '01305 000000',
    travel: { low: 12, high: 17, source: 'Routing data' },
    ...over,
  };
}

function answer(...services: Record<string, unknown>[]) {
  return { generatedAt: '2026-11-10T14:00:00Z', notFound: false, services };
}

describe('parseFind', () => {
  it('reads the services in the order sent', () => {
    const read = parseFind(answer(service(), service({ serviceId: 'svc-b', name: 'Beta' })));
    expect(read?.services.map((item) => item.serviceId)).toEqual(['svc-a', 'svc-b']);
    expect(read?.notFound).toBe(false);
  });

  it('is null for anything that is not an answer, so the page says so rather than show a guess', () => {
    expect(parseFind(null)).toBeNull();
    expect(parseFind({})).toBeNull();
    expect(parseFind({ services: 'x' })).toBeNull();
  });

  it('drops a service with no id or name and keeps the rest', () => {
    const read = parseFind(answer(service({ serviceId: 7 }), service({ name: '' }), service()));
    expect(read?.services).toHaveLength(1);
  });

  it('reads a status it does not know as not updated, never as accepting', () => {
    const read = parseFind(answer(service({ status: 'wide-open' })));
    expect(read?.services[0]?.status).toBe('not-updated');
    expect(read?.services[0]?.figureUnavailable).toBe(true);
  });

  it('treats a service whose status is not updated as having no current figure even if the flag is missing', () => {
    const read = parseFind(answer(service({ status: 'not-updated', figureUnavailable: undefined })));
    expect(read?.services[0]?.figureUnavailable).toBe(true);
  });

  it('keeps the unavailable flag the back end set, and the last figure to show small', () => {
    const read = parseFind(answer(service({ figureUnavailable: true, overdue: true, lastFigure: 8 })));
    expect(read?.services[0]).toMatchObject({ figureUnavailable: true, lastFigure: 8 });
  });

  it('offers a phone number only when it is shaped like one', () => {
    expect(parseFind(answer(service({ phone: 'javascript:alert(1)' })))?.services[0]?.phone).toBeNull();
    expect(parseFind(answer(service()))?.services[0]?.phone).toBe('01305 000000');
  });

  it('reads how many services each group has in all, and drops a count that is not a whole number', () => {
    const read = parseFind({ ...answer(service()), groupTotals: { 'urgent-community-response': 4, bad: 'x', neg: -1 } });
    expect(read?.groupTotals).toEqual({ 'urgent-community-response': 4 });
    expect(parseFind(answer(service()))?.groupTotals).toEqual({});
  });

  it('says when the postcode could not be placed', () => {
    expect(parseFind({ ...answer(service()), notFound: true })?.notFound).toBe(true);
  });
});

describe('toOption', () => {
  it('gives the service card what it shows, with the travel as words and the warnings as checks', () => {
    const [found] = parseFind(answer(service()))!.services;
    const option = toOption(found!);
    expect(option).toMatchObject({
      serviceId: 'svc-a',
      network: null,
      travelText: 'about 12 to 17 min',
      checks: ['Limited: phone to confirm'],
      figureUnavailable: false,
    });
  });

  it('keeps a late figure unavailable on the card', () => {
    const [found] = parseFind(answer(service({ figureUnavailable: true })))!.services;
    expect(toOption(found!).figureUnavailable).toBe(true);
  });
});

function found(id: string, name: string, category: string, status = 'accepting'): FoundService {
  return parseFind(answer(service({ serviceId: id, name, category, status })))!.services[0]!;
}

describe('groupsOf', () => {
  it('makes one group per category with its count, by name of the group', () => {
    const groups = groupsOf([
      found('1', 'A', 'urgent-community-response'),
      found('2', 'B', 'inpatient-beds'),
      found('3', 'C', 'urgent-community-response'),
    ]);
    expect(groups.map((group) => [group.category, group.services.length])).toEqual([
      ['inpatient-beds', 1],
      ['urgent-community-response', 2],
    ]);
    expect(groups[0]?.label.length).toBeGreaterThan(0);
  });

  it('is empty when nothing was found', () => {
    expect(groupsOf([])).toEqual([]);
  });
});

describe('orderServices', () => {
  const list = [
    found('1', 'Zed', 'x', 'accepting'),
    found('2', 'Alpha', 'x', 'not-accepting'),
    found('3', 'Mid', 'x', 'limited'),
  ];

  it('by name ignores status', () => {
    expect(orderServices(list, 'name').map((item) => item.name)).toEqual(['Alpha', 'Mid', 'Zed']);
  });

  it('by travel keeps the order the back end sent, which already is travel then name', () => {
    expect(orderServices(list, 'travel').map((item) => item.name)).toEqual(['Zed', 'Alpha', 'Mid']);
  });

  it('does not change the list it was given', () => {
    const before = list.map((item) => item.name);
    orderServices(list, 'name');
    expect(list.map((item) => item.name)).toEqual(before);
  });
});
