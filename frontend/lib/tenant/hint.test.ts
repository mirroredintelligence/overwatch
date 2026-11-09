import { describe, expect, it } from 'vitest';
import { isTenantLetters, lettersOfCall, lettersOfToken, tenantLetters } from './hint';

const TOKEN = 'EGgUYPNAWmUifbKPQaBGpyS'; // 23 letters

describe('the organisation letters (DEC-1354)', () => {
  it('writes a tenant id with letters only, one to one', () => {
    expect(tenantLetters('fortrus-limited')).toBe('fortrusKlimited');
    expect(tenantLetters('trust-a2')).toBe('trustKaC');
    expect(tenantLetters('0a-9z')).toBe('AaKJz');
    expect(tenantLetters('Not A Tenant')).toBeNull();
    expect(tenantLetters('a')).toBeNull();
  });

  it('reads the letters in front of a link token', () => {
    expect(lettersOfToken(`fortrusKlimited${TOKEN}`)).toBe('fortrusKlimited');
    expect(lettersOfToken(TOKEN)).toBeNull();
    expect(lettersOfToken(`a${TOKEN}`)).toBeNull();
    expect(lettersOfToken(`ab-${TOKEN}`)).toBeNull();
    expect(lettersOfToken(42)).toBeNull();
    expect(lettersOfToken(`${'a'.repeat(32)}${TOKEN}`)).toBeNull();
  });

  it('finds the letters a call names, in its path or in an invitation field', () => {
    const named = `fortrusKlimited${TOKEN}`;
    expect(lettersOfCall({ path: `/identity/invitations/${named}/code` })).toBe('fortrusKlimited');
    expect(lettersOfCall({ path: '/identity/invitation', body: { invitation: named } })).toBe('fortrusKlimited');
    expect(lettersOfCall({ path: '/identity/x', body: { invite: named } })).toBe('fortrusKlimited');
    expect(lettersOfCall({ path: `/links/${TOKEN}` })).toBeNull();
  });

  it('accepts only letters as a hint', () => {
    expect(isTenantLetters('fortrusKlimited')).toBe(true);
    expect(isTenantLetters('a1')).toBe(false);
    expect(isTenantLetters('x')).toBe(false);
    expect(isTenantLetters(undefined)).toBe(false);
  });
});
