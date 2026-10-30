import { describe, expect, it } from 'vitest';
import { LEADER_PRACTITIONERS } from '@/test/msw/handlers/exec';
import { leadersFromBundle } from './leaders';

describe('leadersFromBundle', () => {
  it('reads each leader as an id and a display name, and nothing else', () => {
    expect(leadersFromBundle({ resourceType: 'Bundle', entry: LEADER_PRACTITIONERS.map((resource) => ({ resource })) })).toEqual([
      { id: 'pr-0101', name: 'Sample Lead One' },
      { id: 'pr-0102', name: 'Sample Lead Two' },
    ]);
  });

  it('is an empty list for a bundle with no entry, and refuses an answer that is not a bundle', () => {
    expect(leadersFromBundle({ resourceType: 'Bundle' })).toEqual([]);
    expect(() => leadersFromBundle({ resourceType: 'Patient' })).toThrow();
  });

  it('drops a leader with no id or no name, and keeps no phone, email or role whatever the entry holds', () => {
    const read = leadersFromBundle({
      resourceType: 'Bundle',
      entry: [
        { resource: { resourceType: 'Practitioner', id: 'pr-1', name: [{ text: 'A Lead' }], telecom: [{ value: '07700 900123' }] } },
        { resource: { resourceType: 'Practitioner', id: 'pr-2' } },
        { resource: { resourceType: 'Practitioner', name: [{ text: 'No Id' }] } },
      ],
    });
    expect(read).toEqual([{ id: 'pr-1', name: 'A Lead' }]);
    expect(JSON.stringify(read)).not.toMatch(/07700|telecom/);
  });
});
