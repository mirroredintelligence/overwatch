import { describe, expect, it } from 'vitest';
import { OPTIONS_PARAMETERS } from '@/test/fixtures/options';
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
