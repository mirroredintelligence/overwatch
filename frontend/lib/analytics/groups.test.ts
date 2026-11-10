import { describe, expect, it } from 'vitest';
import { ANALYTICS_OVERVIEW } from '@/test/fixtures/analytics';
import { categoryGroups, districtGroups, drillRows, NOT_PLACED, statusCounts } from './groups';

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

  it('links each row to the service page', () => {
    expect(drillRows(services, { kind: 'status', key: 'accepting' })[0]?.href).toBe('/analytics/services/svc-poole');
  });
});
