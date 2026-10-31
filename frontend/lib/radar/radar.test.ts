import { describe, expect, it } from 'vitest';
import { HOSPITAL_AT_HOME, RADAR_PARTS, UCR_EAST, UCR_FAR, UCR_WEST, WARD_B } from '@/test/fixtures/radar';
import {
  comparable,
  coverSummary,
  coveringPatient,
  groupByLane,
  inLayer,
  laneOf,
  laneOrder,
  overlappingPairs,
  visitingOf,
} from './radar';

const ALL = RADAR_PARTS.options;
const ids = (list: readonly { serviceId: string }[]) => list.map((item) => item.serviceId);

describe('lanes', () => {
  it('a virtual service is remote, a visiting one comes, anything else is a place', () => {
    expect(laneOf(HOSPITAL_AT_HOME)).toBe('remote');
    expect(laneOf(UCR_WEST)).toBe('comes');
    expect(laneOf(WARD_B)).toBe('place');
    expect(laneOf({ ...WARD_B, position: null })).toBe('place');
  });

  it('groups every service into exactly one lane, keeping the order sent', () => {
    const lanes = groupByLane(ALL);
    expect(ids(lanes.comes)).toEqual(['svc-ucr-west', 'svc-ucr-east']);
    expect(ids(lanes.remote)).toEqual(['svc-hospital-at-home']);
    expect(ids(lanes.place)).toEqual(['svc-ward-b']);
  });

  it('the answer to can the patient travel changes only the order of the lanes', () => {
    expect(laneOrder(null)).toEqual(['comes', 'remote', 'place']);
    expect(laneOrder('no')).toEqual(['comes', 'remote', 'place']);
    expect(laneOrder('yes')).toEqual(['place', 'comes', 'remote']);
    expect(laneOrder('help')).toEqual(['comes', 'place', 'remote']);
    for (const answer of [null, 'yes', 'help', 'no'] as const) expect([...laneOrder(answer)].sort()).toEqual(['comes', 'place', 'remote']);
  });

  it('the compare view lines up the services that come or stay remote, never the places', () => {
    expect(ids(comparable(ALL))).toEqual(['svc-ucr-west', 'svc-ucr-east', 'svc-hospital-at-home']);
  });
});

describe('layers', () => {
  it('visiting services, hospital at home and places are separate layers', () => {
    expect(ids(ALL.filter((option) => inLayer(option, 'visiting')))).toEqual(['svc-ucr-west', 'svc-ucr-east']);
    expect(ids(ALL.filter((option) => inLayer(option, 'home')))).toEqual(['svc-hospital-at-home']);
    expect(ids(ALL.filter((option) => inLayer(option, 'places')))).toEqual(['svc-ward-b']);
  });
});

describe('coverage', () => {
  const patient = RADAR_PARTS.patientArea;

  it('lists the visiting services whose area includes the patient', () => {
    expect(ids(coveringPatient([...ALL, UCR_FAR], patient))).toEqual(['svc-ucr-west', 'svc-ucr-east', 'svc-hospital-at-home']);
  });

  it('a patient with no place is covered by nobody (nothing is guessed)', () => {
    expect(coveringPatient(ALL, null)).toEqual([]);
  });

  it('finds the pairs of areas that share ground, once each, and none for a far one', () => {
    const pairs = overlappingPairs([...ALL, UCR_FAR]).map(([a, b]) => `${a.serviceId}+${b.serviceId}`);
    expect(pairs).toEqual(['svc-ucr-west+svc-ucr-east', 'svc-ucr-west+svc-hospital-at-home', 'svc-ucr-east+svc-hospital-at-home']);
    expect(visitingOf([...ALL, UCR_FAR])).toHaveLength(4);
  });

  it('says how many services cover the patient, and that they overlap when more than one', () => {
    expect(coverSummary([UCR_WEST, UCR_EAST, HOSPITAL_AT_HOME])).toBe(
      'This patient is covered by 3 services. Their areas overlap here, so compare them.',
    );
    expect(coverSummary([UCR_WEST])).toBe('This patient is covered by 1 service.');
    expect(coverSummary([])).toBe('No visiting service covers this patient area. Places to go are still listed.');
  });
});
