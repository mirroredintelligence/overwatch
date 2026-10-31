import { describe, expect, it } from 'vitest';
import { OPTIONS_PARAMETERS } from '@/test/fixtures/options';
import { MAP_PARAMETERS } from '@/test/fixtures/map';
import { OPTIONS, OPTIONS_NO_POSTCODE } from '@/test/fixtures/backend-shapes';
import { optionsFromParameters, STALE_AFTER_SECONDS } from './options';

describe('optionsFromParameters (W13)', () => {
  it('keeps the back end order and maps each option and each not-suitable service', () => {
    const view = optionsFromParameters(OPTIONS_PARAMETERS);

    expect(view?.options.map((option) => option.name)).toEqual(['UCR West', 'Community hospital · Ward B', 'Hospital at home']);
    expect(view?.notSuitable).toEqual([
      { serviceId: 'svc-sdec-2', name: 'SDEC · Site 2', reason: 'not accepting since 13:30' },
      { serviceId: 'svc-virtual-ward', name: 'Virtual ward · frailty', reason: 'not updated since 09:02' },
      { serviceId: 'svc-reablement', name: 'Reablement', reason: 'outside the criteria for this district' },
    ]);
  });

  it('builds the travel text from the range, and says nothing where the back end sent none', () => {
    const view = optionsFromParameters(OPTIONS_PARAMETERS);

    expect(view?.options[0].travelText).toBe('about 35 to 50 min');
    expect(view?.options[2].travelText).toBeNull();
  });

  it(`flags data older than ${STALE_AFTER_SECONDS / 3600} hrs, and no earlier`, () => {
    const at = (seconds: number) =>
      optionsFromParameters({
        resourceType: 'Parameters',
        parameter: [
          { name: 'option', part: [
            { name: 'serviceId', valueString: 's' },
            { name: 'name', valueString: 'S' },
            { name: 'status', valueCode: 'accepting' },
            { name: 'criteriaVersion', valueInteger: 1 },
            { name: 'dataAgeSeconds', valueInteger: seconds },
          ] },
        ],
      })?.options[0].staleWarning;

    expect(at(STALE_AFTER_SECONDS)).toBe(false);
    expect(at(STALE_AFTER_SECONDS + 1)).toBe(true);
    expect(at(60)).toBe(false);
  });

  it('shows a status the rules do not know as Not updated, never as accepting', () => {
    const view = optionsFromParameters({
      resourceType: 'Parameters',
      parameter: [
        { name: 'option', part: [
          { name: 'serviceId', valueString: 's' },
          { name: 'name', valueString: 'Odd' },
          { name: 'status', valueCode: 'probably-open' },
          { name: 'criteriaVersion', valueInteger: 1 },
        ] },
      ],
    });
    expect(view?.options[0].status).toBe('not-updated');
  });

  it('reads nothing outside its list: an unknown part is dropped, not passed on', () => {
    const view = optionsFromParameters({
      resourceType: 'Parameters',
      parameter: [
        { name: 'option', part: [
          { name: 'serviceId', valueString: 's' },
          { name: 'name', valueString: 'S' },
          { name: 'status', valueCode: 'accepting' },
          { name: 'criteriaVersion', valueInteger: 1 },
          { name: 'tenantId', valueString: 'tenant-b' },
          { name: 'phone', valueString: '01234 567890' },
        ] },
      ],
    });
    expect(JSON.stringify(view)).not.toContain('tenant-b');
    expect(JSON.stringify(view)).not.toContain('01234');
  });

  it('answers null for anything that is not a Parameters resource', () => {
    expect(optionsFromParameters({ resourceType: 'Bundle' })).toBeNull();
    expect(optionsFromParameters(null)).toBeNull();
  });
});

describe('optionsFromParameters: the map parts (W50)', () => {
  it('reads the patient point, each position, the coverage radius, the travel legs and the flags', () => {
    const view = optionsFromParameters(MAP_PARAMETERS);

    expect(view?.patientArea).toEqual({ lat: 50.7, lon: -2.44 });
    expect(view?.notFound).toBe(false);
    expect(view?.outOfArea).toBe(false);
    expect(view?.options[0].position).toEqual({ lat: 50.72, lon: -2.45 });
    expect(view?.options[0].travel?.legs).toEqual([
      {
        label: 'Patient to UCR West, by road',
        low: 35,
        high: 50,
        how: 'Typical weekday afternoon. The spread is from traffic.',
        source: 'Routing data, updated 12 Oct',
      },
    ]);
    expect(view?.options[2].coverage).toEqual({ lat: 50.71, lon: -2.44, radiusKm: 15 });
    expect(view?.options[2].position).toBeNull();
  });

  it('a network service carries its organisation, and its own organisation is null', () => {
    const view = optionsFromParameters(MAP_PARAMETERS);
    expect(view?.options[3].network).toEqual({ organisation: 'Neighbouring', source: 'Entered by the organisation' });
    expect(view?.options[0].network).toBeNull();
  });

  it('an answer with no map parts gives no positions, no patient point and no flags set', () => {
    const view = optionsFromParameters(OPTIONS_PARAMETERS);
    expect(view?.patientArea).toBeNull();
    expect(view?.options[0].position).toBeNull();
    expect(view?.options[0].travel?.legs).toEqual([]);
    expect(view?.notFound).toBe(false);
  });

  it('an out-of-range coordinate is not a position', () => {
    const view = optionsFromParameters({
      resourceType: 'Parameters',
      parameter: [{ name: 'option', part: [
        { name: 'serviceId', valueString: 's' }, { name: 'name', valueString: 'S' },
        { name: 'status', valueCode: 'accepting' }, { name: 'criteriaVersion', valueInteger: 1 },
        { name: 'lat', valueDecimal: 123 }, { name: 'lon', valueDecimal: -2 },
      ] }],
    });
    expect(view?.options[0].position).toBeNull();
  });
});

describe('optionsFromParameters against the back end\'s own answer (W13, W50, DEC-779)', () => {
  it('reads what filter_result_to_fhir writes: the place, the travel range and its source, the patient point and the figures', () => {
    const view = optionsFromParameters(OPTIONS);

    expect(view?.patientArea).toEqual({ lat: 50.71, lon: -2.44 });
    expect(view?.notFound).toBe(false);
    expect(view?.outOfArea).toBe(false);
    expect(view?.options[0]).toMatchObject({
      serviceId: 'svc-1',
      name: 'UCR West',
      category: 'urgent-community-response',
      status: 'accepting',
      effectiveAvailable: 3,
      unitLabel: 'referrals in the next 2 hrs',
      travelText: 'about 15 to 25 min',
      dataAgeSeconds: 540,
      criteriaVersion: 3,
      fits: ['Falls without injury', 'Frailty'],
      checks: ['Limited: phone to confirm'],
      position: { lat: 50.71, lon: -2.45 },
      coverage: null,
      travel: { low: 15, high: 25, source: 'road estimate', legs: [] },
      network: null,
      phone: null,
    });
    expect(view?.notSuitable).toEqual([{ serviceId: 'svc-3', name: 'Dorchester SDEC', reason: 'Not accepting' }]);
  });

  it('reads an over-capacity service with no figure of its own and no data age, and says nothing about its travel', () => {
    const second = optionsFromParameters(OPTIONS)?.options[1];

    expect(second).toMatchObject({
      status: 'over-capacity',
      overBy: 1,
      effectiveAvailable: null,
      dataAgeSeconds: null,
      staleWarning: false,
      travelText: null,
      travel: null,
      position: null,
      category: null,
    });
  });

  it('reads the two map flags when the back end sends them, and no patient point', () => {
    expect(optionsFromParameters(OPTIONS_NO_POSTCODE)).toMatchObject({
      options: [],
      patientArea: null,
      notFound: true,
      outOfArea: true,
    });
  });

  // The districts to choose from (W50, W9H DEC-1045): the back end sends one `district` part each, in the
  // order to show them, only with a flag. The page keeps only what is a postcode district.
  const withDistricts = (flags: Record<string, boolean>, ...districts: unknown[]) => ({
    resourceType: 'Parameters',
    parameter: [
      ...Object.entries(flags).map(([name, valueBoolean]) => ({ name, valueBoolean })),
      ...districts.map((valueString) => ({ name: 'district', valueString })),
    ],
  });

  it('reads the districts to choose from, in the order sent', () => {
    expect(optionsFromParameters(withDistricts({ notFound: true }, 'DT1', 'DT3', 'BH21'))?.districts).toEqual(['DT1', 'DT3', 'BH21']);
    expect(optionsFromParameters(withDistricts({ outOfArea: true }, 'DT2'))?.districts).toEqual(['DT2']);
  });

  it('keeps only what is a district: no postcode, no lower case, no repeat, no more than twelve', () => {
    const many = Array.from({ length: 20 }, (_, n) => `DT${n + 1}`);
    expect(optionsFromParameters(withDistricts({ notFound: true }, 'DT4 8XX', 'dt4', 'DT4', 'DT4', 7, null, '', 'DT 4', 'DT48X9'))?.districts).toEqual(['DT4']);
    expect(optionsFromParameters(withDistricts({ notFound: true }, ...many))?.districts).toHaveLength(12);
  });

  it('offers none unless the postcode was not found or is outside the area, and none when none were sent', () => {
    expect(optionsFromParameters(withDistricts({}, 'DT1'))?.districts).toEqual([]);
    expect(optionsFromParameters(withDistricts({ notFound: true }))?.districts).toEqual([]);
    expect(optionsFromParameters(OPTIONS_PARAMETERS)?.districts).toEqual([]);
  });
});
