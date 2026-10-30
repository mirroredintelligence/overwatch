import { describe, expect, it } from 'vitest';
import { issuesFromOutcome, organisationValues, pageFieldFor, STEP_FIELDS } from './draft';

// The BFF's mapping between the screen's answers and the back end's step values (R10 $draft), and
// back to the screen's field names. The locked invitation values come from the back end, never from
// the browser.

describe('STEP_FIELDS', () => {
  it('names the organisation step fields, and nothing else', () => {
    expect(STEP_FIELDS.organisation).toEqual(['name', 'odsCode', 'orgType', 'contactName', 'contactRole', 'contact']);
  });
});

describe('organisationValues', () => {
  it('sends the typed name and ODS code, the organisation type and the contact, and only the answers the back end takes', () => {
    expect(
      organisationValues({ name: 'Sample Community Trust', odsCode: 'SAM01', orgType: 'nhs-trust', contactName: 'Sample Person', contactRole: 'Lead', contact: 'contact@example.test' }),
    ).toEqual({
      name: 'Sample Community Trust',
      odsCode: 'SAM01',
      orgType: 'nhs-trust',
      contactName: 'Sample Person',
      contactEmail: 'contact@example.test',
    });
  });

  it('never sends the contact role, which the back end cannot keep (DEC-906)', () => {
    expect(organisationValues({ contactRole: 'Practice manager' })).toEqual({});
  });

  it('sends a phone number as the contact phone, and leaves out what is not given', () => {
    const values = organisationValues({ name: 'Sample Community Trust', contactName: 'Sample Person', contact: '01305 123456' });
    expect(values).toEqual({ name: 'Sample Community Trust', contactName: 'Sample Person', contactPhone: '01305 123456' });
    expect(values).not.toHaveProperty('orgType');
    expect(values).not.toHaveProperty('contactEmail');
  });
});

describe('pageFieldFor', () => {
  it('names the page field an error belongs to: either contact field is the one contact box', () => {
    expect(pageFieldFor('contactEmail')).toBe('contact');
    expect(pageFieldFor('contactPhone')).toBe('contact');
    expect(pageFieldFor('contact')).toBe('contact');
    expect(pageFieldFor('orgType')).toBe('orgType');
    expect(pageFieldFor('contactName')).toBe('contactName');
  });
});

describe('issuesFromOutcome', () => {
  it('turns each issue of the back end’s OperationOutcome into a field and a message, with the field on the page', () => {
    expect(
      issuesFromOutcome({
        resourceType: 'OperationOutcome',
        issue: [
          { severity: 'error', code: 'invalid', diagnostics: 'Enter a contact email or phone number', expression: ['contact'] },
          { severity: 'error', code: 'invalid', diagnostics: 'Choose an organisation type', expression: ['orgType'] },
        ],
      }),
    ).toEqual([
      { field: 'contact', message: 'Enter a contact email or phone number' },
      { field: 'orgType', message: 'Choose an organisation type' },
    ]);
  });

  it('drops an issue with no expression or no text, and never echoes a value', () => {
    expect(issuesFromOutcome({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'invalid' }] })).toEqual([]);
    expect(issuesFromOutcome({ resourceType: 'OperationOutcome', issue: [{ severity: 'error', code: 'invalid', diagnostics: 'x', expression: [] }] })).toEqual([]);
    expect(issuesFromOutcome('not an outcome')).toEqual([]);
  });
});
