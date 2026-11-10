import { describe, expect, it } from 'vitest';
import { ANALYTICS_AREAS, ANALYTICS_OVERVIEW, ANALYTICS_OVERVIEW_AREAS } from '@/test/fixtures/analytics';
import { areaGroups, categoryGroups, districtGroups, drillRows, inTarget, NOT_PLACED, statusCounts } from './groups';

const services = ANALYTICS_OVERVIEW.services;

describe('districtGroups', () => {
  it('makes one group per district, by name, and counts a service in each district it covers', () => {
    const groups = districtGroups(services);
    expect(groups.map((group) => group.label)).toEqual(['BH15', 'BH21', 'BH7', 'Not placed']);
    const bh15 = groups.find((group) => group.label === 'BH15');
    expect(bh15?.services.map((service) => service.name)).toEqual(['Bournemouth SDEC', 'Poole UTC']);
    expect(bh15?.counts).toMatchObject({ accepting: 1, limited: 1 });
  });

  it('puts a service with no district in "Not placed" and never drops it', () => {
    const groups = districtGroups(services);
    const notPlaced = groups.find((group) => group.key === NOT_PLACED);
    expect(notPlaced?.services.map((service) => service.name)).toEqual(['Hospital at home']);
    const seen = new Set(groups.flatMap((group) => group.services.map((service) => service.serviceId)));
    expect(seen.size).toBe(services.length);
  });

  it('has no "Not placed" group when every service has a district', () => {
    const placed = services.filter((service) => service.districts.length > 0);
    expect(districtGroups(placed).some((group) => group.key === NOT_PLACED)).toBe(false);
  });
});

describe('categoryGroups', () => {
  it('lists all eight categories in the board order, with the empty ones counted as zero', () => {
    const groups = categoryGroups(services);
    expect(groups).toHaveLength(8);
    expect(groups.map((group) => group.label)).toEqual([
      'Urgent community response',
      'Same day emergency care',
      'Inpatient beds',
      'Virtual beds',
      'Care packages',
      'Urgent treatment',
      'Mental health crisis',
      'Other',
    ]);
    expect(groups[0]?.services).toEqual([]);
    expect(groups[2]?.services.map((service) => service.name)).toEqual(['Ward Z']);
  });
});

describe('statusCounts', () => {
  it('counts the five statuses of a list of services', () => {
    expect(statusCounts(services)).toEqual({ accepting: 1, limited: 1, 'not-accepting': 1, 'over-capacity': 1, 'not-updated': 1 });
  });
});

describe('drillRows', () => {
  it('lists the services of a district by name, not by status', () => {
    const rows = drillRows(services, { kind: 'district', key: 'BH7' });
    expect(rows.map((row) => row.name)).toEqual(['Bournemouth SDEC', 'Ward Z']);
  });

  it('lists the services of a status or a group', () => {
    expect(drillRows(services, { kind: 'status', key: 'limited' }).map((row) => row.serviceId)).toEqual(['svc-sdec']);
    expect(drillRows(services, { kind: 'group', key: 'reablement' }).map((row) => row.serviceId)).toEqual(['svc-reab']);
    expect(drillRows(services, { kind: 'district', key: NOT_PLACED }).map((row) => row.serviceId)).toEqual(['svc-hah']);
  });

  it('gives a figure only for a current figure: an old one reads unavailable, never a number', () => {
    const rows = new Map(drillRows(services, { kind: 'status', key: 'not-updated' }).map((row) => [row.serviceId, row]));
    expect(rows.get('svc-hah')?.figure).toBeNull();
    const over = drillRows(services, { kind: 'status', key: 'over-capacity' })[0];
    expect(over?.figure).toBe('+2');
    const fresh = drillRows(services, { kind: 'status', key: 'accepting' })[0];
    expect(fresh?.figure).toBe('8');
  });

  it('never gives a number for a figure that is not current, even if the payload carries one', () => {
    const hostile = [
      { ...services[0]!, status: 'accepting' as const, figureCurrent: false, available: 5, overBy: null },
      { ...services[2]!, status: 'over-capacity' as const, figureCurrent: false, available: null, overBy: 3 },
    ];
    expect(drillRows(hostile, { kind: 'status', key: 'accepting' })[0]?.figure).toBeNull();
    expect(drillRows(hostile, { kind: 'status', key: 'over-capacity' })[0]?.figure).toBeNull();
  });

  it('links each row to the service page', () => {
    expect(drillRows(services, { kind: 'status', key: 'accepting' })[0]?.href).toBe('/analytics/services/svc-poole');
  });
});

describe('areaGroups (DEC-1375)', () => {
  const rows = ANALYTICS_OVERVIEW_AREAS.services;

  it('makes one group per area in the order given, with the places as its second line, and "Not placed" last', () => {
    const groups = areaGroups(rows, ANALYTICS_AREAS);
    expect(groups.map((group) => group.label)).toEqual(['Area One', 'Area Two', 'Network-wide', 'Not placed']);
    expect(groups.map((group) => group.sub)).toEqual(['Alpha · Beta', 'Gamma', 'Services working across areas', undefined]);
    expect(groups[0]?.services.map((service) => service.name)).toEqual(['Poole UTC', 'Ward Z']);
  });

  it('counts each service once, so the groups add up to every service', () => {
    const groups = areaGroups(rows, ANALYTICS_AREAS);
    expect(groups.reduce((sum, group) => sum + group.services.length, 0)).toBe(rows.length);
    expect(new Set(groups.flatMap((group) => group.services.map((service) => service.serviceId))).size).toBe(rows.length);
  });

  it('keeps an area with no service, and has no "Not placed" group when every service has an area', () => {
    const placed = rows.filter((service) => service.area !== null).filter((service) => service.area !== 'area-two');
    const groups = areaGroups(placed, ANALYTICS_AREAS);
    expect(groups.find((group) => group.key === 'area-two')?.services).toEqual([]);
    expect(groups.some((group) => group.key === NOT_PLACED)).toBe(false);
  });

  it('drills by the area id, and by "Not placed" for a service with no area', () => {
    const inOne = drillRows(rows, { kind: 'area', key: 'area-one' }).map((row) => row.name);
    expect(inOne).toEqual(['Poole UTC', 'Ward Z']);
    expect(rows.filter((service) => inTarget(service, { kind: 'area', key: NOT_PLACED })).map((service) => service.name)).toEqual(['Hospital at home']);
    expect(rows.filter((service) => inTarget(service, { kind: 'area', key: 'network' })).map((service) => service.name)).toEqual(['Bournemouth SDEC']);
  });
});
