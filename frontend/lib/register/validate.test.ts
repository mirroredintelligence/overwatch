import { describe, expect, it } from 'vitest';
import { validateOrganisation } from './validate';

// The organisation step's client-side checks, in screen order. The back end checks the same fields
// again on save (R10 validate_step); these messages are the screen's own wording.

describe('validateOrganisation', () => {
  it('returns the problems of an empty step, in screen order, with the screen wording', () => {
    expect(validateOrganisation({})).toEqual([
      { field: 'name', message: 'Enter the organisation name' },
      { field: 'odsCode', message: 'Enter the ODS code' },
      { field: 'orgType', message: 'Choose the organisation type' },
      { field: 'contactName', message: 'Enter your name' },
      { field: 'contactRole', message: 'Enter your role' },
      { field: 'contact', message: 'Enter an email address or phone number' },
    ]);
  });

  it('treats spaces alone as empty', () => {
    const issues = validateOrganisation({ name: '  ', odsCode: ' ', contactName: '   ', contactRole: ' ', contact: '  ' });
    expect(issues.map((i) => i.field)).toEqual(['name', 'odsCode', 'orgType', 'contactName', 'contactRole', 'contact']);
  });

  it('accepts an email or a UK phone number as the contact', () => {
    const base = { name: 'Sample Community Trust', odsCode: 'SAM01', orgType: 'nhs-trust', contactName: 'Sample Person', contactRole: 'Lead' };
    expect(validateOrganisation({ ...base, contact: 'contact@example.test' })).toEqual([]);
    expect(validateOrganisation({ ...base, contact: '01305 123456' })).toEqual([]);
  });

  it('refuses a contact that is neither an email nor a phone number, with the same message as empty', () => {
    const issues = validateOrganisation({ name: 'Sample Community Trust', odsCode: 'SAM01', orgType: 'nhs-trust', contactName: 'Sample Person', contactRole: 'Lead', contact: 'not a contact' });
    expect(issues).toEqual([{ field: 'contact', message: 'Enter an email address or phone number' }]);
  });
});
