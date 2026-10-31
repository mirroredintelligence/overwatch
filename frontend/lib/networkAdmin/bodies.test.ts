import { describe, expect, it } from 'vitest';
import { FhirError } from '@/lib/fhir/client';
import { agreementBody, emptyBody, inviteBody, reasonBody } from './bodies';

const refused = (fn: () => unknown) => {
  try {
    fn();
    return false;
  } catch (error) {
    return error instanceof FhirError && error.status === 400;
  }
};

describe('inviteBody', () => {
  it('turns the organisation code into the back end’s one field', () => {
    expect(inviteBody({ organisationCode: 'sample-area-c' })).toEqual({ tenant_id: 'sample-area-c' });
  });
  it.each([null, [], 'x', {}, { organisationCode: 'A' }, { organisationCode: 'a' }, { organisationCode: '-ab' }, { organisationCode: 'a b' }, { organisationCode: 'x'.repeat(32) }, { organisationCode: 'ab', other: 1 }])('refuses %j', (body) => {
    expect(refused(() => inviteBody(body))).toBe(true);
  });
});

describe('agreementBody', () => {
  it('keeps the reference and the version', () => {
    expect(agreementBody({ reference: 'DSA-2026-2', version: 2 })).toEqual({ reference: 'DSA-2026-2', version: 2 });
  });
  it.each([{}, { reference: 'x' }, { version: 2 }, { reference: '', version: 2 }, { reference: '-x', version: 2 }, { reference: 'x y', version: 2 }, { reference: 'x', version: 0 }, { reference: 'x', version: 2.5 }, { reference: 'x', version: '2' }, { reference: 'x', version: 2, content: 'c' }])('refuses %j', (body) => {
    expect(refused(() => agreementBody(body))).toBe(true);
  });
});

describe('reasonBody', () => {
  it('accepts only a fixed code', () => {
    expect(reasonBody({ reason: 'other' })).toEqual({ reason: 'other' });
    expect(refused(() => reasonBody({ reason: 'Other' }))).toBe(true);
    expect(refused(() => reasonBody({}))).toBe(true);
  });
});

describe('emptyBody', () => {
  const post = (body?: string) => new Request('https://x.example.test/', { method: 'POST', body });
  it('accepts none, an empty one and an empty object', async () => {
    await expect(emptyBody(post())).resolves.toBeUndefined();
    await expect(emptyBody(post('  '))).resolves.toBeUndefined();
    await expect(emptyBody(post('{}'))).resolves.toBeUndefined();
  });
  it('refuses a body that holds anything, or is not JSON', async () => {
    await expect(emptyBody(post('{"a":1}'))).rejects.toBeInstanceOf(FhirError);
    await expect(emptyBody(post('nope'))).rejects.toBeInstanceOf(FhirError);
    await expect(emptyBody(post('[]'))).rejects.toBeInstanceOf(FhirError);
  });
});
