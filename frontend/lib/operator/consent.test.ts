import { describe, expect, it } from 'vitest';
import { consentInvitationBody } from './bodies';
import { parseConsent } from './views';

describe('the admin consent invitation body (DEC-1316)', () => {
  it('passes one plain work email address, trimmed', () => {
    expect(consentInvitationBody({ email: ' jane.admin@example-trust.nhs.uk ' })).toEqual({ email: 'jane.admin@example-trust.nhs.uk' });
  });

  it.each(['', 'no-at', 'a@', '@b.org', 'a b@c.org', 'a..b@c.org', 'Jane <j@c.org>', 'x'.repeat(260) + '@c.org'])('refuses %j', (email) => {
    expect(() => consentInvitationBody({ email })).toThrow();
  });

  it('refuses a body that names a tenant or anything else, and one that is not an object', () => {
    expect(() => consentInvitationBody({ email: 'a@b.org', tenantId: 'other-org' })).toThrow();
    expect(() => consentInvitationBody(null)).toThrow();
    expect(() => consentInvitationBody([])).toThrow();
  });
});

describe('what the page is told of an invitation', () => {
  const raw = { inviteId: 'inv-1', emailMasked: 'j***@example.org', status: 'pending', createdAt: '2026-11-01T09:00:00Z', expiresAt: '2026-11-08T09:00:00Z', consentedAt: null, reason: null, emailHash: 'x', stateHash: 'y' };

  it('keeps the masked address and the state, and drops everything else', () => {
    const view = parseConsent({ invitation: raw, recorded: true });
    expect(view).toEqual({ invitation: { emailMasked: 'j***@example.org', status: 'pending', createdAt: '2026-11-01T09:00:00Z', expiresAt: '2026-11-08T09:00:00Z', consentedAt: null, reason: null }, recorded: true });
    expect(JSON.stringify(view)).not.toMatch(/inviteId|emailHash|stateHash/);
  });

  it('reads no invitation as null', () => {
    expect(parseConsent({ invitation: null }).invitation).toBeNull();
  });

  it('refuses a status that is not one of the four, and a body that is not an object', () => {
    expect(() => parseConsent({ invitation: { ...raw, status: 'approved' } })).toThrow();
    expect(() => parseConsent('x')).toThrow();
  });
});
