import { describe, expect, it } from 'vitest';
import { organisationsOf, ownRow } from './orgs';

// The organisations of a network view, for the filter chips and the own-row marker (TEN-069, TEN-070).
// A network row names its organisation by display name only; the page gives each an opaque reference
// (`org-1`, `org-2`) so a chip can be told apart without the name or any id being an attribute.

const names = ['Sample Area B', 'Sample Area A', 'Sample Area B', 'Sample Area D'];

describe('organisationsOf', () => {
  it('lists each organisation once: the viewer’s own first, then the others alphabetically', () => {
    expect(organisationsOf(names, 'Sample Area A').map((o) => o.name)).toEqual(['Sample Area A', 'Sample Area B', 'Sample Area D']);
  });

  it('lists them alphabetically when the viewer’s own is not there or not known', () => {
    expect(organisationsOf(names, null).map((o) => o.name)).toEqual(['Sample Area A', 'Sample Area B', 'Sample Area D']);
    expect(organisationsOf(['Sample Area B', 'Sample Area C'], 'Sample Area A').map((o) => o.name)).toEqual(['Sample Area B', 'Sample Area C']);
  });

  it('gives each an opaque reference that does not hold the name', () => {
    const refs = organisationsOf(names, 'Sample Area A').map((o) => o.ref);
    expect(refs).toEqual(['org-1', 'org-2', 'org-3']);
  });

  it('marks the own organisation', () => {
    expect(organisationsOf(names, 'Sample Area A').map((o) => o.own)).toEqual([true, false, false]);
  });

  it('is a list of none for none', () => {
    expect(organisationsOf([], 'Sample Area A')).toEqual([]);
  });
});

describe('ownRow', () => {
  it('is true only for the viewer’s own organisation’s name', () => {
    expect(ownRow('Sample Area A', 'Sample Area A')).toBe(true);
    expect(ownRow('Sample Area B', 'Sample Area A')).toBe(false);
    expect(ownRow('Sample Area A', null)).toBe(false);
  });
});
