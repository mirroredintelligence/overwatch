import { describe, expect, it } from 'vitest';
import { mapScopeList } from './backend';

const SCHEME = 'https://diucs.example/fhir/CodeSystem';

// The back end's scope list (R10, U23): a FHIR List whose entries carry the flag as a coding and
// the name, category, reason and registration state as extensions.
const entry = (id: string, flag: string, extensions: Array<[string, Record<string, string>]>) => ({
  item: { reference: `HealthcareService/${id}` },
  flag: { coding: [{ system: `${SCHEME}/scope-flag`, code: flag }] },
  extension: extensions.map(([name, value]) => ({ url: `${SCHEME}/scope-list/${name}`, ...value })),
});

const LIST = {
  resourceType: 'List',
  id: 'scope-list',
  status: 'current',
  entry: [
    entry('s1', 'in-pilot', [
      ['name', { valueString: 'UCR West' }],
      ['category', { valueCode: 'urgent-community-response' }],
      ['reason', { valueString: '' }],
      ['registration-status', { valueCode: 'live' }],
    ]),
    entry('s2', 'in-pilot', [
      ['name', { valueString: 'UCR East' }],
      ['category', { valueCode: 'urgent-community-response' }],
      ['reason', { valueString: '' }],
      ['registration-status', { valueCode: 'submitted' }],
    ]),
    entry('s9', 'later', [
      ['name', { valueString: 'Reablement' }],
      ['category', { valueCode: 'reablement' }],
      ['reason', { valueString: 'Not in the pilot yet' }],
    ]),
  ],
};

describe('mapScopeList', () => {
  it('maps each entry to the browser shape, with its id taken from the item reference', () => {
    const { entries } = mapScopeList(LIST);
    expect(entries).toHaveLength(3);
    expect(entries[0]).toEqual({
      serviceId: 's1',
      name: 'UCR West',
      category: 'urgent-community-response',
      flag: 'in-pilot',
      registrationState: 'live',
    });
  });

  it('reads a submitted registration as in review, and an entry with no status as not invited', () => {
    const { entries } = mapScopeList(LIST);
    expect(entries[1]?.registrationState).toBe('in-review');
    expect(entries[2]?.registrationState).toBe('not-invited');
  });

  it('keeps a reason, and leaves out an empty one', () => {
    const { entries } = mapScopeList(LIST);
    expect(entries[2]).toEqual({
      serviceId: 's9',
      name: 'Reablement',
      category: 'reablement',
      flag: 'later',
      registrationState: 'not-invited',
      reason: 'Not in the pilot yet',
    });
    expect(entries[0]).not.toHaveProperty('reason');
  });

  it('refuses a body that is not a scope list', () => {
    expect(() => mapScopeList({ resourceType: 'Bundle' })).toThrow();
  });
});
