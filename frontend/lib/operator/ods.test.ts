import { describe, expect, it, vi } from 'vitest';
import { normaliseOdsCode, normaliseOdsName, organisationTypeForRole, recordOds, searchOds } from './ods';

// The shapes below are the NHS ORD answers seen on 2026-10-31 for an NHS trust, a practice and a search.
const SEARCH = {
  Organisations: [{ Name: 'THE ARDLEIGH SURGERY', OrgId: 'F81044', Status: 'Active', PostCode: 'CO7 7LD', PrimaryRoleId: 'RO177' }],
};
const PRACTICE = {
  Organisation: {
    Name: 'THE ARDLEIGH SURGERY',
    OrgId: { root: '2.16.840.1.113883.2.1.3.2.4.18.48', assigningAuthorityName: 'HSCIC', extension: 'F81044' },
    Status: 'Active',
    GeoLoc: { Location: { PostCode: 'CO7 7LD' } },
    LastChangeDate: '2025-01-01',
    Roles: { Role: [
      { id: 'RO177', primaryRole: true, Status: 'Active' },
      { id: 'RO76', primaryRole: false, Status: 'Active' },
      { id: 'RO999', primaryRole: false, Status: 'Inactive' },
    ] },
    Rels: { Rel: [
      { id: 'RE4', Status: 'Active', Target: { OrgId: { extension: '06T' }, PrimaryRoleId: { id: 'RO98' } } },
      { id: 'RE8', Status: 'Inactive', Target: { OrgId: { extension: 'OLD1' }, PrimaryRoleId: { id: 'RO1' } } },
    ] },
  },
};

function ord(routes: Record<string, unknown>) {
  return vi.fn(async (url: string | URL | Request) => {
    const path = String(url).replace('https://directory.spineservices.nhs.uk/ORD/2-0-0', '');
    const hit = Object.keys(routes).find((key) => path.startsWith(key));
    return hit === undefined ? new Response('', { status: 404 }) : new Response(JSON.stringify(routes[hit]), { status: 200 });
  }) as unknown as typeof fetch;
}

describe('the ODS helpers', () => {
  it('reads a friendly name and an ODS code as the search and the record take them', () => {
    expect(normaliseOdsName('  Ardleigh   Surgery ')).toBe('Ardleigh Surgery');
    expect(normaliseOdsName('   ')).toBeNull();
    expect(normaliseOdsCode(' f81044 ')).toBe('F81044');
    expect(normaliseOdsCode('F81 044')).toBeNull();
  });

  it('suggests a type from a primary role, and nothing for a role it does not know', () => {
    expect(organisationTypeForRole('RO197')).toBe('nhs-trust');
    expect(organisationTypeForRole('RO177')).toBe('gp-practice');
    expect(organisationTypeForRole('RO272')).toBeNull();
    expect(organisationTypeForRole(null)).toBeNull();
  });
});

describe('searchOds', () => {
  it('searches active organisations by the friendly name and returns each hit', async () => {
    const fetcher = ord({ '/organisations?': SEARCH });
    const hits = await searchOds('ardleigh surgery', fetcher);
    expect(hits).toEqual([{ code: 'F81044', name: 'THE ARDLEIGH SURGERY', postcode: 'CO7 7LD', primaryRole: 'RO177', status: 'Active' }]);
    const url = String((fetcher as unknown as { mock: { calls: unknown[][] } }).mock.calls[0]![0]);
    expect(url).toContain('Name=ardleigh%20surgery');
    expect(url).toContain('Status=Active');
  });

  it('gives an empty list for an empty name, and null when the directory cannot be reached', async () => {
    expect(await searchOds('  ', ord({}))).toEqual([]);
    const broken = vi.fn(async () => {
      throw new TypeError('offline');
    });
    expect(await searchOds('ardleigh', broken as unknown as typeof fetch)).toBeNull();
  });
});

describe('recordOds', () => {
  it('reads the record with its active roles and active links, and names them', async () => {
    const fetcher = ord({
      '/organisations/F81044': PRACTICE,
      '/roles/RO177': { Roles: [{ id: 'RO177', displayName: 'PRESCRIBING COST CENTRE' }] },
      '/roles/RO76': { Roles: [{ id: 'RO76', displayName: 'GP PRACTICE' }] },
      '/organisations/06T': { Organisation: { Name: 'NHS ESSEX ICB - 06T' } },
    });
    const record = await recordOds('f81044', fetcher);
    expect(record).toMatchObject({
      code: 'F81044',
      name: 'THE ARDLEIGH SURGERY',
      status: 'Active',
      postcode: 'CO7 7LD',
      primaryRole: 'RO177',
      lastChangedAt: '2025-01-01',
      suggestedOrganisationType: 'gp-practice',
    });
    expect(record?.roles).toEqual([
      { id: 'RO177', name: 'PRESCRIBING COST CENTRE', primary: true },
      { id: 'RO76', name: 'GP PRACTICE', primary: false },
    ]);
    expect(record?.links).toEqual([{ relationship: 'RE4', code: '06T', name: 'NHS ESSEX ICB - 06T', role: 'RO98' }]);
  });

  it('reads a non-NHS record as the real API shapes it, with no NHS type suggested', async () => {
    const fortrus = {
      Organisation: {
        Name: 'FORTRUS LIMITED',
        OrgId: { root: '2.16.840.1.113883.2.1.3.2.4.18.48', assigningAuthorityName: 'HSCIC', extension: '8HT86' },
        Status: 'Active',
        LastChangeDate: '2026-04-01',
        GeoLoc: { Location: { PostCode: 'SG1 2DX' } },
        Roles: { Role: [{ id: 'RO157', primaryRole: true, Status: 'Active' }] },
        Rels: { Rel: [] },
      },
    };
    const record = await recordOds('8HT86', ord({ '/organisations/8HT86': fortrus, '/roles/RO157': { Roles: [{ id: 'RO157', displayName: 'NON-NHS ORGANISATION' }] } }));
    expect(record).toMatchObject({ code: '8HT86', name: 'FORTRUS LIMITED', postcode: 'SG1 2DX', primaryRole: 'RO157', suggestedOrganisationType: null });
    expect(record?.roles).toEqual([{ id: 'RO157', name: 'NON-NHS ORGANISATION', primary: true }]);
  });

  it('gives nothing for a code that is not one, or an organisation that is not there', async () => {
    expect(await recordOds('no such code!', ord({}))).toBeNull();
    expect(await recordOds('ZZZZZ', ord({}))).toBeNull();
  });
});
