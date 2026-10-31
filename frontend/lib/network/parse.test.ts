// @vitest-environment node
import { describe, expect, it } from 'vitest';
import {
  BOARD_BODY,
  CRITERIA_BODY,
  DIRECTORY_BODY,
  DIRECTORY_HISTORY_BODY,
  NETWORKS_BODY,
  PHONES_BODY,
  SYSTEM_NOW_BODY,
  WEEK_BODY,
  WEEK_WITHHELD_BODY,
  boardEntry,
} from '@/test/fixtures/network';
import {
  NetworkParseError,
  parseBoard,
  parseCriteria,
  parseDirectory,
  parseNetworks,
  parsePhones,
  parseSystemNow,
  parseWeek,
} from './parse';

// TEN-068: the network answers as the front end reads them. One parser per answer, strict, used twice:
// on the back end's own JSON (snake_case) and on the BFF's (camelCase, what the first one made). A
// shape it does not know is an error, never a guess, and a field it does not know is dropped, so a
// back end that sent a tenant id by mistake would still not reach a page.

const json = <T>(value: T): unknown => JSON.parse(JSON.stringify(value));

describe('parseNetworks', () => {
  it('reads the list of networks the viewer may see', () => {
    expect(parseNetworks(NETWORKS_BODY, 'backend')).toEqual([
      { id: 'net-sample', name: 'Sample Network', systemName: 'Sample capacity', pathwayName: 'Sample pathway', timeZone: 'Europe/London' },
    ]);
  });

  it('reads an empty list as none', () => {
    expect(parseNetworks({ networks: [] }, 'backend')).toEqual([]);
  });

  it.each([null, {}, { networks: 'x' }, { networks: [{ id: 'trust-a', name: 'x', system_name: 'a', pathway_name: 'b', time_zone: 'Europe/London' }] }])(
    'refuses %j',
    (body) => {
      expect(() => parseNetworks(body, 'backend')).toThrow(NetworkParseError);
    },
  );
});

describe('parseBoard', () => {
  it('reads the board of the back end, entry by entry', () => {
    const board = parseBoard(BOARD_BODY, 'backend');
    expect(board.generatedAt).toBe('2026-10-23T13:12:00+00:00');
    expect(board.entries).toHaveLength(4);
    expect(board.entries[0]).toEqual({
      rowRef: 'lst-0001',
      organisationName: 'Sample Area A',
      serviceName: 'UCR West',
      category: 'urgent-community-response',
      presentation: 'shown',
      status: 'accepting',
      unitLabel: 'beds',
      effectiveAvailable: 4,
      overBy: null,
      used: 2,
      established: 6,
      reportedAt: '2026-10-23T13:08:00+00:00',
      staleWarning: false,
      wasDueAt: null,
    });
    expect(board.pressure).toBe('normal');
    expect(board.systemName).toBe('Sample capacity');
  });

  it('reads a paused listing as unavailable, with no status and no figure', () => {
    const paused = parseBoard(BOARD_BODY, 'backend').entries[3]!;
    expect(paused).toMatchObject({ presentation: 'unavailable', status: null, unitLabel: null, established: null, used: null });
  });

  it('reads its own answer again (the BFF sends what the first read made)', () => {
    const once = parseBoard(BOARD_BODY, 'backend');
    expect(parseBoard(json(once), 'bff')).toEqual(once);
  });

  it('drops a field it does not know, so a tenant id sent by mistake never reaches a page', () => {
    const body = { ...BOARD_BODY, tenantId: 'trust-b', entries: [boardEntry({ sourceTenantId: 'trust-b', source_tenant_id: 'trust-b', grant_id: 'g-1', source_service_id: 'svc-9' })] };
    const text = JSON.stringify(parseBoard(body, 'backend'));
    expect(text).not.toMatch(/trust-b|g-1|svc-9|sourceTenant|tenantId|source_/);
  });

  it.each([
    ['an unknown status', boardEntry({ status: 'busy' })],
    ['an unknown presentation', boardEntry({ presentation: 'hidden' })],
    ['a missing organisation', boardEntry({ organisation_name: undefined })],
    ['a negative count', boardEntry({ used: -1 })],
    ['a count that is text', boardEntry({ established: '6' })],
    ['a time that is not one', boardEntry({ reported_at: 'yesterday' })],
    ['a stale flag that is not a boolean', boardEntry({ stale_warning: 'no' })],
    ['an unknown category', boardEntry({ category: 'private-clinic' })],
  ])('refuses %s', (_name, entry) => {
    expect(() => parseBoard({ ...BOARD_BODY, entries: [entry] }, 'backend')).toThrow(NetworkParseError);
  });

  it('refuses a board with no time, an unknown pressure, or entries that are not a list', () => {
    expect(() => parseBoard({ ...BOARD_BODY, generated_at: undefined }, 'backend')).toThrow(NetworkParseError);
    expect(() => parseBoard({ ...BOARD_BODY, pressure: 'calm' }, 'backend')).toThrow(NetworkParseError);
    expect(() => parseBoard({ ...BOARD_BODY, entries: {} }, 'backend')).toThrow(NetworkParseError);
    expect(() => parseBoard(null, 'backend')).toThrow(NetworkParseError);
  });

  it('puts nothing of a rejected body in the error', () => {
    try {
      parseBoard({ ...BOARD_BODY, entries: [boardEntry({ status: 'Secret-Value-9' })] }, 'backend');
      expect.unreachable();
    } catch (error) {
      expect(String((error as Error).message)).not.toContain('Secret-Value-9');
    }
  });
});

describe('parseDirectory', () => {
  it('reads the entries, with the service line, the place and the opening hours', () => {
    const directory = parseDirectory(DIRECTORY_BODY, 'backend');
    expect(directory.entries).toHaveLength(2);
    expect(directory.entries[0]).toMatchObject({
      rowRef: 'lst-0001',
      contactLabel: 'Service line',
      contactPhone: '01632 960010',
      location: { name: 'West hub', postalDistrict: 'DT4', city: 'Sampletown', latitude: 50.6, longitude: -2.45 },
      openingHours: [{ position: 0, days: [0, 1, 2, 3, 4], allDay: false, start: '08:00', end: '20:00' }],
      endedAt: null,
      endReason: null,
    });
    expect(directory.entries[1]).toMatchObject({ contactLabel: null, contactPhone: null, location: null });
  });

  it('reads the history: what ended and why', () => {
    const history = parseDirectory(DIRECTORY_HISTORY_BODY, 'backend');
    expect(history.entries.map((e) => [e.serviceName, e.endReason])).toEqual([
      ['Former service', 'left'],
      ['Stopped service', 'grant-ended'],
    ]);
  });

  it('reads its own answer again', () => {
    const once = parseDirectory(DIRECTORY_BODY, 'backend');
    expect(parseDirectory(json(once), 'bff')).toEqual(once);
  });

  it('refuses an unknown end reason and a day that is not one', () => {
    expect(() => parseDirectory({ ...DIRECTORY_BODY, entries: [{ ...DIRECTORY_BODY.entries[0], end_reason: 'sacked' }] }, 'backend')).toThrow(NetworkParseError);
    const hours = [{ position: 0, days: [9], all_day: true, start: null, end: null }];
    expect(() => parseDirectory({ ...DIRECTORY_BODY, entries: [{ ...DIRECTORY_BODY.entries[0], opening_hours: hours }] }, 'backend')).toThrow(NetworkParseError);
  });
});

describe('parseCriteria', () => {
  it('reads the current criteria of a service, as codes', () => {
    const criteria = parseCriteria(CRITERIA_BODY, 'backend');
    expect(criteria.entries[0]).toEqual({
      rowRef: 'lst-0001',
      organisationName: 'Sample Area A',
      serviceName: 'UCR West',
      version: 3,
      ageMin: 18,
      ageMax: 120,
      districts: ['DT4', 'DT5'],
      accepts: ['frailty', 'wound-care'],
      excludes: ['dementia'],
      reviewBy: '2027-01-15',
      endedAt: null,
      endReason: null,
    });
  });

  it('reads its own answer again, and refuses a need that is not one', () => {
    const once = parseCriteria(CRITERIA_BODY, 'backend');
    expect(parseCriteria(json(once), 'bff')).toEqual(once);
    expect(() => parseCriteria({ ...CRITERIA_BODY, entries: [{ ...CRITERIA_BODY.entries[0], accepts: ['magic'] }] }, 'backend')).toThrow(NetworkParseError);
  });
});

describe('parseSystemNow', () => {
  it('reads every status count, the pressure and the alert state', () => {
    const now = parseSystemNow(SYSTEM_NOW_BODY, 'backend');
    expect(now.services).toBe(4);
    expect(now.organisations).toBe(3);
    expect(now.byStatus).toEqual({ accepting: 1, limited: 1, 'not-accepting': 0, 'over-capacity': 0, 'not-updated': 1, 'out-of-hours': 0, unavailable: 1 });
    expect(now.alert).toEqual({ raised: false, level: 'normal', limitedOrWorse: 1, watchFrom: 3, highFrom: 5 });
    expect(parseSystemNow(json(now), 'bff')).toEqual(now);
  });

  it('refuses a count that is missing, so a status is never shown as zero by a guess', () => {
    const byStatus: Record<string, number> = { ...SYSTEM_NOW_BODY.by_status };
    delete byStatus['limited'];
    expect(() => parseSystemNow({ ...SYSTEM_NOW_BODY, by_status: byStatus }, 'backend')).toThrow(NetworkParseError);
  });
});

describe('parsePhones', () => {
  it('reads the service line of each row, null when none was shared', () => {
    const phones = parsePhones(PHONES_BODY, 'backend');
    expect(phones.phones.map((p) => [p.serviceName, p.contactPhone])).toEqual([
      ['UCR West', '01632 960010'],
      ['Care packages north', null],
      ['Paused listing', null],
    ]);
    expect(phones.organisations).toBe(3);
    expect(parsePhones(json(phones), 'bff')).toEqual(phones);
  });
});

describe('parseWeek', () => {
  it('reads the measures, hidden ones with no value', () => {
    const week = parseWeek(WEEK_BODY, 'backend');
    expect(week.weekStart).toBe('2026-10-19');
    expect(week.withheld).toBe(false);
    expect(week.hoursSampled).toEqual({ label: 'hours sampled', value: 134, hidden: false });
    expect(week.statusShare['over-capacity']).toEqual({ label: 'over capacity', value: null, hidden: true });
    expect(week.pressureHours.high.hidden).toBe(true);
    expect(week.pressureOverTime).toEqual([
      { hour: '2026-10-19T00:00:00+00:00', pressure: 'normal' },
      { hour: '2026-10-19T01:00:00+00:00', pressure: 'watch' },
    ]);
    expect(parseWeek(json(week), 'bff')).toEqual(week);
  });

  it('reads a withheld week: every measure hidden, no series', () => {
    const week = parseWeek(WEEK_WITHHELD_BODY, 'backend');
    expect(week.withheld).toBe(true);
    expect(week.pressureOverTime).toEqual([]);
  });

  it('refuses a hidden measure that carries a value, and a visible one that has none', () => {
    const hiddenWithValue = { ...WEEK_BODY, on_time_pct: { label: 'x', value: 75, hidden: true } };
    const shownWithout = { ...WEEK_BODY, on_time_pct: { label: 'x', value: null, hidden: false } };
    expect(() => parseWeek(hiddenWithValue, 'backend')).toThrow(NetworkParseError);
    expect(() => parseWeek(shownWithout, 'backend')).toThrow(NetworkParseError);
  });
});
