import { describe, expect, it } from 'vitest';
import { normaliseDistrict, serviceValues, validateService, type ServiceAnswers } from './service';

// Registration step 3 (W25): the checks and the mapping. The criteria it sets are what advisors filter
// on, so the boundary cases are tested here. Sample values only.

const TODAY = '2026-10-30';

// A complete answer: every field valid. Each test changes one thing from it.
const FULL: ServiceAnswers = {
  category: 'urgent-community-response',
  referralMethods: ['phone', 'systmone'],
  spoaPhone: '01305 123456',
  acceptingDays: ['mon', 'tue', 'wed', 'thu', 'fri'],
  acceptingStart: '08:00',
  acceptingEnd: '18:00',
  needs: ['frailty', 'wound-care'],
  ageMin: '65',
  ageMax: null,
  excludedNeeds: ['suspected-fracture'],
  noExclusions: false,
  ownerRole: 'Community matron',
  ownerEmail: 'owner@example.test',
  reviewBy: '2027-01-31',
  districts: ['DT3', 'DT4'],
};

describe('validateService', () => {
  it('returns exactly the three problems of the canvas case, in order: category, phone, owner', () => {
    const issues = validateService(
      { ...FULL, category: undefined, spoaPhone: '0123', ownerRole: '' },
      { fixedSite: true, today: TODAY },
    );
    expect(issues).toEqual([
      { field: 'category', message: 'Choose a category' },
      { field: 'spoaPhone', message: 'Enter a full phone number, for example 01632 960123' },
      { field: 'ownerRole', message: 'Enter who owns the criteria' },
    ]);
  });

  it('has an empty phone message that differs from the invalid one', () => {
    expect(validateService({ ...FULL, spoaPhone: '  ' }, { fixedSite: true, today: TODAY })).toEqual([
      { field: 'spoaPhone', message: 'Enter a phone number the coordination team can call' },
    ]);
  });

  it('accepts a 10 or 11 digit UK number, with spaces or hyphens, and refuses others', () => {
    for (const ok of ['01305 123456', '01305-123456', '07700900456', '01305123456']) {
      expect(validateService({ ...FULL, spoaPhone: ok }, { fixedSite: true, today: TODAY })).toEqual([]);
    }
    for (const bad of ['0123', '013051234567', '+44 1305 123456', 'abcdefghij']) {
      expect(validateService({ ...FULL, spoaPhone: bad }, { fixedSite: true, today: TODAY })[0]?.field).toBe('spoaPhone');
    }
  });

  it('wants the oldest age to be at least the youngest, or no limit', () => {
    expect(validateService({ ...FULL, ageMin: '65', ageMax: '64' }, { fixedSite: true, today: TODAY })).toEqual([
      { field: 'ageMax', message: 'Oldest age must be at least the youngest age' },
    ]);
    expect(validateService({ ...FULL, ageMin: '65', ageMax: '65' }, { fixedSite: true, today: TODAY })).toEqual([]);
    expect(validateService({ ...FULL, ageMin: '65', ageMax: null }, { fixedSite: true, today: TODAY })).toEqual([]);
    expect(validateService({ ...FULL, ageMin: '121' }, { fixedSite: true, today: TODAY })[0]?.field).toBe('ageMin');
  });

  it('asks for "No exclusions" or the needs you do not accept', () => {
    expect(validateService({ ...FULL, excludedNeeds: [], noExclusions: false }, { fixedSite: true, today: TODAY })).toEqual([
      { field: 'excludedNeeds', message: 'Choose the needs you do not accept, or No exclusions' },
    ]);
    expect(validateService({ ...FULL, excludedNeeds: [], noExclusions: true }, { fixedSite: true, today: TODAY })).toEqual([]);
  });

  it('wants a review date in the future, not today or before', () => {
    expect(validateService({ ...FULL, reviewBy: TODAY }, { fixedSite: true, today: TODAY })).toEqual([
      { field: 'reviewBy', message: 'Enter a review date in the future' },
    ]);
    expect(validateService({ ...FULL, reviewBy: '' }, { fixedSite: true, today: TODAY })[0]?.field).toBe('reviewBy');
  });

  it('wants districts for a visiting service, and not for a fixed site', () => {
    expect(validateService({ ...FULL, districts: [] }, { fixedSite: false, today: TODAY })).toEqual([
      { field: 'districts', message: 'Choose the districts you cover' },
    ]);
    expect(validateService({ ...FULL, districts: [] }, { fixedSite: true, today: TODAY })).toEqual([]);
    expect(validateService({ ...FULL, districts: [] }, { fixedSite: undefined, today: TODAY })).toEqual([]);
  });

  it('asks for a referral method and at least one need', () => {
    const issues = validateService({ ...FULL, referralMethods: [], needs: [] }, { fixedSite: true, today: TODAY });
    expect(issues.map((issue) => issue.message)).toEqual(['Choose how the coordination team can refer', 'Choose at least one need you accept']);
  });

  it('asks for the accepting days and times, as the screen words them', () => {
    expect(validateService({ ...FULL, acceptingDays: [] }, { fixedSite: true, today: TODAY })).toEqual([
      { field: 'acceptingDays', message: 'Choose the days you accept referrals' },
    ]);
    expect(validateService({ ...FULL, acceptingStart: '8am' }, { fixedSite: true, today: TODAY })).toEqual([
      { field: 'acceptingStart', message: 'Enter a time like 08:00' },
    ]);
  });
});

describe('normaliseDistrict', () => {
  it('accepts a district in any case and puts it in capitals, and rejects a bare area', () => {
    expect(normaliseDistrict('dt5')).toBe('DT5');
    expect(normaliseDistrict(' dt4 ')).toBe('DT4');
    expect(normaliseDistrict('DT')).toBeNull();
    expect(normaliseDistrict('DT4 8XX')).toBeNull();
    expect(normaliseDistrict('')).toBeNull();
  });
});

describe('serviceValues', () => {
  it('sends the coded values the back end takes, with the invitation’s service name', () => {
    expect(
      serviceValues(
        {
          category: 'urgent-community-response',
          referralMethods: ['phone', 'systmone'],
          spoaPhone: '01305 123456',
          acceptingDays: ['mon', 'fri'],
          acceptingStart: '08:00',
          acceptingEnd: '18:00',
          needs: ['frailty', 'wound-care'],
          ageMin: 65,
          ageMax: null,
          excludedNeeds: ['suspected-fracture'],
          ownerRole: 'Community matron',
          ownerEmail: 'owner@example.test',
          reviewBy: '2027-01-31',
          districts: ['DT3', 'DT4'],
        },
        'UCR West',
      ),
    ).toEqual({
      serviceName: 'UCR West',
      category: 'urgent-community-response',
      referralMethods: 'phone,systmone',
      spoaPhone: '01305 123456',
      acceptingDays: 'mon,fri',
      acceptingStart: '08:00',
      acceptingEnd: '18:00',
      needs: 'frailty,wound-care',
      ageMin: 65,
      noAgeLimit: true,
      excludedNeeds: 'suspected-fracture',
      ownerRole: 'Community matron',
      ownerEmail: 'owner@example.test',
      reviewBy: '2027-01-31',
      districts: 'DT3,DT4',
    });
  });

  it('sends an oldest age as a number, and "no exclusions" as a flag with no list', () => {
    const values = serviceValues({ ageMin: 18, ageMax: 64, excludedNeeds: [], noExclusions: true }, 'UCR West');
    expect(values).toMatchObject({ ageMin: 18, ageMax: 64, noExclusions: true });
    expect(values).not.toHaveProperty('excludedNeeds');
    expect(values).not.toHaveProperty('noAgeLimit');
  });
});
