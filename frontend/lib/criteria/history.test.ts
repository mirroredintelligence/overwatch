import { describe, expect, it } from 'vitest';
import { mapHistory, waitingVersion } from './history';

// The back end's history (U30, `GET /Basic?subject=`): a searchset of Basic resources, each with its
// version, its status and its review date. Nothing else of a version is in it.
const basic = (id: string, version: number, status: string, reviewBy: string) => ({
  resourceType: 'Basic',
  id,
  meta: { versionId: String(version) },
  code: { coding: [{ code: 'service-criteria' }] },
  subject: { reference: 'HealthcareService/s1' },
  status,
  reviewBy,
});

const BUNDLE = {
  resourceType: 'Bundle',
  type: 'searchset',
  total: 3,
  entry: [
    { resource: basic('basic-3', 3, 'current', '2026-09-12') },
    { resource: basic('basic-4', 4, 'pending-approval', '2026-12-12') },
    { resource: basic('basic-1', 1, 'superseded', '2026-03-01') },
  ],
};

describe('mapHistory', () => {
  it('maps each version with its words for the status, newest first', () => {
    const versions = mapHistory(BUNDLE);
    expect(versions.map((v) => v.version)).toEqual([4, 3, 1]);
    expect(versions[0]).toEqual({ version: 4, status: 'waiting', reviewBy: '2026-12-12', criteriaId: 'basic-4' });
    expect(versions[1]?.status).toBe('current');
    expect(versions[2]?.status).toBe('replaced');
  });

  it('refuses a body that is not a bundle', () => {
    expect(() => mapHistory({ resourceType: 'Basic' })).toThrow();
  });
});

describe('waitingVersion', () => {
  it('finds the version waiting for approval, and none when there is none', () => {
    const versions = mapHistory(BUNDLE);
    expect(waitingVersion(versions)?.criteriaId).toBe('basic-4');
    expect(waitingVersion(versions.filter((v) => v.status !== 'waiting'))).toBeNull();
  });
});
