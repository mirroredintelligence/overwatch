import { describe, expect, it } from 'vitest';
import { GRANTS, NETWORK, ONLY_IN_A, recordsFor, SHARED_IDS, TENANTS } from './tenants';

// The fixture every tenancy test builds on (TEN-047, audit D 7.2). It is built to make a mistake
// visible: the same identifiers in tenant A and tenant B, so a handler that forgets the tenant returns
// the wrong record instead of a 404, and distinct fictional names, so a wrong record is not mistaken
// for the right one. Nothing in it is a real organisation, host, number or person.

const A = TENANTS.A;
const B = TENANTS.B;
const C = TENANTS.C;

describe('the three tenants and the network', () => {
  it('has tenants A and B, both members of one network, and C, which is not', () => {
    expect([...NETWORK.memberIds].sort()).toEqual([A.id, B.id]);
    expect(NETWORK.memberIds).not.toContain(C.id);
    expect(NETWORK.id).toMatch(/^net-/);
  });

  it('gives every tenant its own host, name and id', () => {
    for (const field of ['id', 'host', 'displayName'] as const) {
      expect(new Set([A[field], B[field], C[field]]).size).toBe(3);
    }
  });

  it('has hosts that are sample hosts under .test and ids that are tenant ids, not network ids', () => {
    for (const tenant of [A, B, C]) {
      expect(tenant.host).toMatch(/\.example\.test$/);
      expect(tenant.id).toMatch(/^[a-z0-9][a-z0-9-]{1,30}$/);
      expect(tenant.id.startsWith('net-')).toBe(false);
    }
  });
});

describe('overlapping identifiers', () => {
  it('has the same service id, case reference, phone ending and registration id in A and B', () => {
    const a = recordsFor(A.id)!;
    const b = recordsFor(B.id)!;
    expect(a.services.map((s) => s.id)).toContain(SHARED_IDS.serviceId);
    expect(b.services.map((s) => s.id)).toContain(SHARED_IDS.serviceId);
    expect(a.cases.map((c) => c.reference)).toContain(SHARED_IDS.caseReference);
    expect(b.cases.map((c) => c.reference)).toContain(SHARED_IDS.caseReference);
    expect(a.phoneEnding).toBe(SHARED_IDS.phoneEnding);
    expect(b.phoneEnding).toBe(SHARED_IDS.phoneEnding);
    expect(a.registrationId).toBe(SHARED_IDS.registrationId);
    expect(b.registrationId).toBe(SHARED_IDS.registrationId);
  });

  it('gives the shared ids different content in A and B, so the wrong record is not mistaken for the right one', () => {
    const a = recordsFor(A.id)!;
    const b = recordsFor(B.id)!;
    const name = (r: typeof a) => r.services.find((s) => s.id === SHARED_IDS.serviceId)!.name;
    const note = (r: typeof a) => r.cases.find((c) => c.reference === SHARED_IDS.caseReference)!.note;
    expect(name(a)).not.toBe(name(b));
    expect(note(a)).not.toBe(note(b));
  });

  it('has an id that exists only in tenant A, in no other tenant', () => {
    expect(recordsFor(A.id)!.services.map((s) => s.id)).toContain(ONLY_IN_A.serviceId);
    for (const other of [B, C]) {
      expect(recordsFor(other.id)!.services.map((s) => s.id)).not.toContain(ONLY_IN_A.serviceId);
      expect(recordsFor(other.id)!.cases.map((c) => c.reference)).not.toContain(ONLY_IN_A.caseReference);
    }
  });

  it('knows no records for a tenant it does not know', () => {
    expect(recordsFor('nobody')).toBeUndefined();
  });
});

describe('grants', () => {
  it('has one active, one ended and one pending grant', () => {
    expect(GRANTS.map((g) => g.state).sort()).toEqual(['active', 'ended', 'pending']);
  });

  it('names the network and a grantor tenant on every grant', () => {
    for (const grant of GRANTS) {
      expect(grant.networkId).toBe(NETWORK.id);
      expect([A.id, B.id, C.id]).toContain(grant.grantorId);
    }
  });
});

describe('what the fixture must not hold', () => {
  it('has no real-looking person, phone number, postcode or NHS number', () => {
    const text = JSON.stringify([TENANTS, NETWORK, GRANTS, recordsFor(A.id), recordsFor(B.id), recordsFor(C.id)]);
    expect(text).not.toMatch(/\b\d{3} \d{3} \d{4}\b/);
    expect(text).not.toMatch(/\b0[1-9]\d{8,9}\b/);
    expect(text).not.toMatch(/\b[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2}\b/);
    expect(text).not.toMatch(/@/);
  });
});
