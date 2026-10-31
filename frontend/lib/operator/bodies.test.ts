import { describe, expect, it } from 'vitest';
import { createTenantBody } from './bodies';

const RECORD = {
  code: 'F81044',
  name: 'THE ARDLEIGH SURGERY',
  status: 'Active',
  postcode: 'CO7 7LD',
  primaryRole: 'RO177',
  roles: [{ id: 'RO177', name: 'PRESCRIBING COST CENTRE', primary: true }],
  links: [{ code: '06T', name: 'NHS ESSEX ICB - 06T', role: 'RO98' }],
  lastChangedAt: '2025-01-01',
};

const BASE = { displayName: 'Ardleigh', legalName: 'Ardleigh Ltd', organisationType: 'gp-practice', odsCode: 'F81044' };

describe('createTenantBody: the NHS record the operator confirmed (DEC-1314)', () => {
  it('passes a valid record through, with its roles and links', () => {
    expect(createTenantBody({ ...BASE, odsRecord: RECORD }).odsRecord).toEqual(RECORD);
  });

  it('passes a record with no postcode, roles or links', () => {
    const minimal = { code: 'F81044', name: 'X', status: 'Active', postcode: null, primaryRole: null, roles: [], links: [], lastChangedAt: null };
    expect(createTenantBody({ ...BASE, odsRecord: minimal }).odsRecord).toEqual(minimal);
  });

  it('refuses a record with an unexpected field, a long list, or a missing name', () => {
    expect(() => createTenantBody({ ...BASE, odsRecord: { ...RECORD, extra: 'x' } })).not.toThrow();
    expect(() => createTenantBody({ ...BASE, odsRecord: { ...RECORD, roles: Array.from({ length: 21 }, () => RECORD.roles[0]) } })).toThrow();
    expect(() => createTenantBody({ ...BASE, odsRecord: { ...RECORD, name: undefined } })).toThrow();
  });
});
