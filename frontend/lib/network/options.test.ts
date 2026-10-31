import { describe, expect, it } from 'vitest';
import { networkOptionsToParts, parseNetworkOptions } from './options';

// WB11 (docs/design/network-ui.md section 9, the options variant): what the advisor's network options are as
// the back end answers them (`GET /network/{id}/options`, routes_network.py `options_to_dict`) and as the
// BFF passes them on, and the rows the advisor's existing option cards read. Fails closed.

const OPTION = {
  row_ref: 'lst-0002',
  organisation_name: 'Sample Area B',
  service_name: 'Virtual ward frailty',
  category: 'hospital-at-home-or-virtual-ward',
  status: 'limited',
  effective_available: 1,
  over_by: null,
  unit_label: 'beds',
  data_age_seconds: 1200,
  fits: ['Covers this postcode', 'Takes frailty'],
  warnings: ['Limited: phone to confirm'],
  criteria_version: 3,
  review_by: '2027-04-29',
  contact_label: 'Service line',
  contact_phone: '01632 960010',
  position: { lat: 52.0, lon: -1.5 },
  travel: { low_minutes: 12, high_minutes: 24 },
};
const BODY = {
  options: [OPTION],
  not_suitable: [{ row_ref: 'lst-0003', organisation_name: 'Sample Area D', service_name: 'Care packages north', reason: 'not accepting' }],
  generated_at: '2026-10-30T10:00:00+00:00',
  patient: { lat: 52.0, lon: -1.4 },
  not_found: false,
  out_of_area: false,
  system_name: 'Sample capacity',
  pathway_name: 'Sample pathway',
  time_zone: 'Europe/London',
};

const camel = (key: string) => key.replace(/_([a-z])/g, (_m, c: string) => c.toUpperCase());
function toBff(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(toBff);
  if (typeof value === 'object' && value !== null) return Object.fromEntries(Object.entries(value).map(([k, v]) => [camel(k), toBff(v)]));
  return value;
}

describe('parseNetworkOptions', () => {
  it('reads what the back end answers', () => {
    const answer = parseNetworkOptions(BODY, 'backend');
    expect(answer.options).toHaveLength(1);
    expect(answer.options[0]).toMatchObject({ rowRef: 'lst-0002', organisationName: 'Sample Area B', serviceName: 'Virtual ward frailty', status: 'limited', dataAgeSeconds: 1200, criteriaVersion: 3, contactPhone: '01632 960010' });
    expect(answer.options[0]?.position).toEqual({ lat: 52, lon: -1.5 });
    expect(answer.options[0]?.travel).toEqual({ lowMinutes: 12, highMinutes: 24 });
    expect(answer.notSuitable).toEqual([{ rowRef: 'lst-0003', organisationName: 'Sample Area D', serviceName: 'Care packages north', reason: 'not accepting' }]);
    expect(answer.patient).toEqual({ lat: 52, lon: -1.4 });
    expect(answer.systemName).toBe('Sample capacity');
  });

  it('reads the BFF’s answer in the same way', () => {
    expect(parseNetworkOptions(toBff(BODY), 'bff')).toEqual(parseNetworkOptions(BODY, 'backend'));
  });

  it('reads a row with no place, no number and no travel', () => {
    const bare = { ...OPTION, position: null, travel: null, contact_label: null, contact_phone: null, unit_label: null, data_age_seconds: null };
    const [option] = parseNetworkOptions({ ...BODY, options: [bare] }, 'backend').options;
    expect(option).toMatchObject({ position: null, travel: null, contactLabel: null, contactPhone: null, unitLabel: null, dataAgeSeconds: null });
  });

  it('drops a field it does not know, so a tenant or a grant sent by mistake never reaches a page', () => {
    const leaky = { ...BODY, options: [{ ...OPTION, tenant_id: 'tenant-b', grant_id: 'grant-1' }], tenant_id: 'x' };
    const text = JSON.stringify(parseNetworkOptions(leaky, 'backend'));
    expect(text).not.toMatch(/tenant|grant/);
  });

  it.each([
    ['not an object', 'x'],
    ['no options', { ...BODY, options: undefined }],
    ['a status the board does not know', { ...BODY, options: [{ ...OPTION, status: 'busy' }] }],
    ['a paused status', { ...BODY, options: [{ ...OPTION, status: null }] }],
    ['a place out of range', { ...BODY, options: [{ ...OPTION, position: { lat: 95, lon: 0 } }] }],
    ['a travel range backwards', { ...BODY, options: [{ ...OPTION, travel: { low_minutes: 30, high_minutes: 10 } }] }],
    ['a negative age', { ...BODY, options: [{ ...OPTION, data_age_seconds: -1 }] }],
    ['a review date that is not a date', { ...BODY, options: [{ ...OPTION, review_by: 'soon' }] }],
    ['a row with no reference', { ...BODY, options: [{ ...OPTION, row_ref: undefined }] }],
    ['no time', { ...BODY, generated_at: undefined }],
    ['a flag that is text', { ...BODY, not_found: 'no' }],
    ['a patient place out of range', { ...BODY, patient: { lat: 0, lon: 200 } }],
  ])('refuses %s', (_name, body) => {
    expect(() => parseNetworkOptions(body, 'backend')).toThrow();
  });
});

describe('networkOptionsToParts', () => {
  const parts = networkOptionsToParts(parseNetworkOptions(BODY, 'backend'));

  it('gives the advisor’s option cards the rows: the reference stands for the service, the organisation is its label', () => {
    expect(parts.options).toHaveLength(1);
    expect(parts.options[0]).toMatchObject({
      serviceId: 'lst-0002',
      name: 'Virtual ward frailty',
      category: 'hospital-at-home-or-virtual-ward',
      status: 'limited',
      effectiveAvailable: 1,
      unitLabel: 'beds',
      travelText: 'about 12 to 24 min',
      dataAgeSeconds: 1200,
      staleWarning: false,
      criteriaVersion: 3,
      fits: ['Covers this postcode', 'Takes frailty'],
      checks: ['Limited: phone to confirm'],
      phone: '01632 960010',
      network: { organisation: 'Sample Area B', source: '' },
      position: { lat: 52, lon: -1.5 },
      coverage: null,
    });
    expect(parts.options[0]?.travel).toMatchObject({ low: 12, high: 24, legs: [] });
  });

  it('names the organisation on each row that is not suitable, with the reason', () => {
    expect(parts.notSuitable).toEqual([{ serviceId: 'lst-0003', name: 'Care packages north', reason: 'not accepting', organisation: 'Sample Area D' }]);
  });

  it('carries the patient’s area, the flags and no district chips (the case’s own district is the tenant’s)', () => {
    expect(parts).toMatchObject({ patientArea: { lat: 52, lon: -1.4 }, notFound: false, outOfArea: false, districts: [] });
  });

  it('says a figure over two hours old is old', () => {
    const old = networkOptionsToParts(parseNetworkOptions({ ...BODY, options: [{ ...OPTION, data_age_seconds: 7201 }] }, 'backend'));
    expect(old.options[0]?.staleWarning).toBe(true);
  });

  it('never gives a row a booking: a network row has no way to be requested', () => {
    expect(parts.options.every((option) => option.network !== null)).toBe(true);
  });
});
