import { describe, expect, it } from 'vitest';
import { apiValues, measureCodeOf, reportingValues, validateApi, validateReporting } from './reporting';

// Registration step 4, how the service reports capacity (W26), and the API answers. The chips the
// applicant sees are not all back-end codes: "Virtual beds free" is the same measure as "Beds free".

const VALID = {
  counts: 'referrals',
  usualLow: '0',
  usualHigh: '8',
  cadence: 'every-2-hrs',
  channel: 'text',
  holderName: 'Sample Ward team',
  contactMobile: '07700 900456',
};

describe('measureCodeOf', () => {
  it('gives each chip its back-end measure, and two beds chips the same one', () => {
    expect(measureCodeOf('referrals')).toBe('referrals-acceptable');
    expect(measureCodeOf('beds')).toBe('free-beds');
    expect(measureCodeOf('virtual-beds')).toBe('free-beds');
    expect(measureCodeOf('slots')).toBe('free-slots');
    expect(measureCodeOf('packages')).toBe('packages-free');
  });

  it('has no measure for "Other", which the screen refuses (H-359)', () => {
    expect(measureCodeOf('other')).toBeNull();
    expect(measureCodeOf('made-up')).toBeNull();
  });
});

describe('validateReporting', () => {
  it('asks for each required answer, in screen order, with the screen wording', () => {
    expect(validateReporting({})).toEqual([
      { field: 'counts', message: 'Choose what you count' },
      { field: 'usualLow', message: 'Enter the lowest usual number' },
      { field: 'usualHigh', message: 'Enter the highest usual number' },
      { field: 'cadence', message: 'Choose how often you report' },
      { field: 'channel', message: 'Choose how you will report' },
      { field: 'holderName', message: 'Enter who holds this phone' },
    ]);
  });

  it('refuses "Other" as a count, with the same message as nothing chosen', () => {
    expect(validateReporting({ ...VALID, counts: 'other' })).toEqual([{ field: 'counts', message: 'Choose what you count' }]);
  });

  it('wants the highest usual number to be at least the lowest', () => {
    expect(validateReporting({ ...VALID, usualLow: '5', usualHigh: '2' })).toEqual([
      { field: 'usualHigh', message: 'Highest usual number must be at least the lowest' },
    ]);
    expect(validateReporting({ ...VALID, usualLow: '5', usualHigh: '5' })).toEqual([]);
  });

  it('wants a UK mobile for text and for the app, and an email for email', () => {
    expect(validateReporting({ ...VALID, contactMobile: '0770090045' })).toEqual([
      { field: 'contactMobile', message: 'Enter a UK mobile number, like 07700 900456' },
    ]);
    expect(validateReporting({ ...VALID, channel: 'push', contactMobile: '' }).map((i) => i.field)).toEqual(['contactMobile']);
    expect(validateReporting({ ...VALID, channel: 'email', contactMobile: '', contactEmail: 'nope' })).toEqual([
      { field: 'contactEmail', message: 'Enter an email address' },
    ]);
    expect(validateReporting({ ...VALID, channel: 'email', contactMobile: '', contactEmail: 'reports@example.test' })).toEqual([]);
  });
});

describe('validateApi', () => {
  it('asks for nothing when there is no API', () => {
    expect(validateApi({ wanted: false })).toEqual([]);
  });

  it('wants an https address and the other three details when there is one', () => {
    expect(validateApi({ wanted: true, name: 'Sample API', address: 'http://example.test', connection: 'REST', dataType: 'Referrals' })).toEqual([
      { field: 'address', message: 'Enter the API address, starting https://' },
    ]);
    expect(validateApi({ wanted: true, address: 'https://api.example.test' })).toEqual([
      { field: 'name', message: 'Enter the API name' },
      { field: 'connection', message: 'Choose a connection type' },
      { field: 'dataType', message: 'Choose a data type' },
    ]);
  });
});

describe('reportingValues', () => {
  it('sends the back end’s codes, the usual range as two numbers, and the contact the channel needs', () => {
    expect(
      reportingValues({
        measure: 'referrals-acceptable',
        usualRange: [0, 8],
        cadence: 'every-2-hrs',
        channel: 'text',
        holderName: 'Sample Ward team',
        contactMobile: '07700900456',
      }),
    ).toEqual({
      measure: 'referrals-acceptable',
      usualLow: 0,
      usualHigh: 8,
      cadence: 'every-2-hrs',
      channel: 'text',
      holderName: 'Sample Ward team',
      contactMobile: '07700900456',
    });
  });

  it('maps "Virtual beds free" to the beds measure, and sends an email as the contact email', () => {
    const values = reportingValues({ measure: 'virtual-beds', usualRange: [1, 2], cadence: 'once-a-day', channel: 'email', holderName: 'Team', contactEmail: 'r@example.test' });
    expect(values).toMatchObject({ measure: 'free-beds', channel: 'email', contactEmail: 'r@example.test' });
    expect(values).not.toHaveProperty('contactMobile');
  });
});

describe('apiValues', () => {
  it('sends the API answers in the back end’s names, and only "wanted" when there is none', () => {
    expect(apiValues({ wanted: true, name: 'Sample API', address: 'https://api.example.test', connection: 'REST', dataType: 'Referrals' })).toEqual({
      wanted: true,
      name: 'Sample API',
      address: 'https://api.example.test',
      connection: 'REST',
      dataType: 'Referrals',
    });
    expect(apiValues({ wanted: false })).toEqual({ wanted: false });
  });
});
