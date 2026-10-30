import { describe, expect, it } from 'vitest';
import { normalisePostcode } from './postcode';
import { locationValues } from './draft';
import { validateLocation } from './validate';

// The location step's checks and its mapping to the back end (R10 LocationStep). Sample postcodes only.

describe('normalisePostcode', () => {
  it('puts a UK postcode in its usual form: capitals with one space before the last three characters', () => {
    expect(normalisePostcode('dt48xx')).toBe('DT4 8XX');
    expect(normalisePostcode(' dt4  8xx ')).toBe('DT4 8XX');
    expect(normalisePostcode('SW1A 1AA')).toBe('SW1A 1AA');
  });

  it('is null for anything that is not a postcode', () => {
    expect(normalisePostcode('')).toBeNull();
    expect(normalisePostcode('DT4')).toBeNull();
    expect(normalisePostcode('12345')).toBeNull();
  });
});

describe('validateLocation', () => {
  it('asks whether there is a fixed site first, and stops there', () => {
    expect(validateLocation({})).toEqual([{ field: 'fixedSite', message: 'Choose whether you have a fixed site' }]);
  });

  it('needs nothing else for a visiting service', () => {
    expect(validateLocation({ fixedSite: false })).toEqual([]);
  });

  it('checks each fixed-site answer in screen order with the screen wording', () => {
    expect(validateLocation({ fixedSite: true })).toEqual([
      { field: 'postcode', message: 'Enter a postcode' },
      { field: 'address', message: 'Choose the address' },
      { field: 'siteName', message: 'Enter the site name' },
      { field: 'siteType', message: 'Choose a site type' },
      { field: 'opening', message: 'Choose the opening days, or 24 hours' },
    ]);
  });

  it('refuses a postcode that is not one, with the postcode message', () => {
    expect(validateLocation({ fixedSite: true, postcode: 'DT4', addressId: 'a1', siteName: 'x', siteType: 'ward', allDay: true })).toEqual([
      { field: 'postcode', message: 'Enter a full postcode' },
    ]);
  });

  it('accepts a time only in the form 08:00, and wants the closing time after the opening time', () => {
    const base = { fixedSite: true, postcode: 'DT4 8XX', addressId: 'a1', siteName: 'x', siteType: 'ward', days: [0] };
    expect(validateLocation({ ...base, opens: '8:00', closes: '20:00' })).toEqual([
      { field: 'opens', message: 'Enter a time like 08:00' },
    ]);
    expect(validateLocation({ ...base, opens: '08:00', closes: '25:00' })).toEqual([
      { field: 'closes', message: 'Enter a time like 08:00' },
    ]);
    expect(validateLocation({ ...base, opens: '20:00', closes: '08:00' })).toEqual([
      { field: 'closes', message: 'The closing time must be after the opening time' },
    ]);
    expect(validateLocation({ ...base, opens: '08:00', closes: '08:00' })).toEqual([
      { field: 'closes', message: 'The closing time must be after the opening time' },
    ]);
    expect(validateLocation({ ...base, opens: '08:00', closes: '20:00' })).toEqual([]);
  });

  it('needs no days or times for a 24-hour service', () => {
    expect(
      validateLocation({ fixedSite: true, postcode: 'DT4 8XX', addressId: 'a1', siteName: 'x', siteType: 'clinic', allDay: true }),
    ).toEqual([]);
  });
});

describe('locationValues', () => {
  it('sends only the fixed-site answer for a visiting service', () => {
    expect(locationValues({ fixedSite: false })).toEqual({ fixedSite: false });
  });

  it('sends a fixed site in the back end’s names: the normalised postcode, the address, the hours as text', () => {
    expect(
      locationValues({
        fixedSite: true,
        postcode: 'dt4 8xx',
        addressId: 'a1',
        address: 'Sample House, Dorchester, DT4 8XX',
        siteName: 'Sample Ward',
        siteType: 'ward',
        hours: { days: [0, 1, 4], allDay: false, opens: '08:00', closes: '20:00' },
      }),
    ).toEqual({
      fixedSite: true,
      postcode: 'DT4 8XX',
      address: 'Sample House, Dorchester, DT4 8XX',
      siteName: 'Sample Ward',
      siteType: 'ward',
      openingDays: 'mon,tue,fri',
      openingStart: '08:00',
      openingEnd: '20:00',
    });
  });

  it('sends a 24-hour service as open24h, with no days or times', () => {
    const values = locationValues({
      fixedSite: true,
      postcode: 'DT4 8XX',
      address: 'Sample House, Dorchester, DT4 8XX',
      siteName: 'Sample Ward',
      siteType: 'ward',
      hours: { days: [], allDay: true },
    });
    expect(values).toMatchObject({ open24h: true });
    expect(values).not.toHaveProperty('openingDays');
  });
});
