import { describe, expect, it } from 'vitest';
import { FhirError } from '@/lib/fhir/client';
import { chooseNetwork, namedNetwork, ownedNetworks } from './network';
import type { NetworkRow } from './views';

const row = (id: string, over: Partial<NetworkRow> = {}): NetworkRow => ({
  id,
  name: id,
  isOwner: true,
  membershipId: 'mem-1',
  membershipStatus: 'active',
  agreementReference: null,
  agreementVersion: null,
  acceptedAgreementVersion: null,
  agreementBehind: false,
  ...over,
});
const status = (fn: () => unknown): number | null => {
  try {
    fn();
    return null;
  } catch (error) {
    return error instanceof FhirError ? error.status : -1;
  }
};

describe('which networks an owner runs', () => {
  it('are the ones it owns and is active in: a membership that was only offered, or that is a member’s, is not', () => {
    const all = [row('net-a'), row('net-b', { isOwner: false }), row('net-c', { membershipStatus: 'invited' })];
    expect(ownedNetworks(all).map((n) => n.id)).toEqual(['net-a']);
  });
});

describe('chooseNetwork', () => {
  const one = [row('net-a')];
  const two = [row('net-a'), row('net-b')];

  it('takes the only one when none is named', () => {
    expect(chooseNetwork(one, null).id).toBe('net-a');
  });
  it('is a 404 for none, named or not', () => {
    expect(status(() => chooseNetwork([], null))).toBe(404);
    expect(status(() => chooseNetwork([], 'net-a'))).toBe(404);
  });
  it('is a 400 for several when none is named: the page must choose', () => {
    expect(status(() => chooseNetwork(two, null))).toBe(400);
  });
  it('takes the named one when it is offered, and the one 404 when it is not', () => {
    expect(chooseNetwork(two, 'net-b').id).toBe('net-b');
    expect(status(() => chooseNetwork(two, 'net-z'))).toBe(404);
    expect(status(() => chooseNetwork(one, 'net-z'))).toBe(404);
  });
});

describe('namedNetwork', () => {
  const at = (query: string) => new Request(`https://x.example.test/api/bff/x${query}`);
  it('is the networkId key, or null', () => {
    expect(namedNetwork(at(''))).toBeNull();
    expect(namedNetwork(at('?networkId=net-sample'))).toBe('net-sample');
  });
  it('refuses what is not a network id', () => {
    expect(status(() => namedNetwork(at('?networkId=trust-a')))).toBe(400);
  });
});
