import { describe, expect, it } from 'vitest';
import { unsignedToken } from '@/test/applicant/backend';
import { TENANTS } from '@/test/tenants';
import { reporterSessionFor } from './signin';

// The applicant's session, made from the back end's answer to a right code (W23, DEC-900 to DEC-901).
// A pure function: the answer, the host the request came to, the device the code was checked on, and
// the clock. It returns a session only when every fact the session needs is one the BFF can vouch
// for; anything else is null, and the route writes nothing.

const NOW = new Date('2026-10-30T10:00:00Z');
const SUB = 'person-sample-1';
const HOST = 'tenant-a.example.test';
const DEVICE = 'Dev1ceIdSampleValue_ab';
const EXPIRES = '2026-10-30T12:00:00Z';
const TOKEN = unsignedToken(SUB, Date.parse(EXPIRES) / 1000);

function answer(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    token: TOKEN,
    expiresAt: EXPIRES,
    role: 'reporter',
    tenant: TENANTS.A.id,
    registrationId: 'REG-SAMPLE-1',
    serviceId: 'SVC-SAMPLE-1',
    serviceName: 'Community nursing',
    ...overrides,
  };
}

const input = { host: HOST, deviceId: DEVICE, now: NOW };

describe('reporterSessionFor', () => {
  it('makes a reporter session for the answer’s tenant and the request host, with the person from the token', () => {
    expect(reporterSessionFor(answer(), input)).toEqual({
      role: 'reporter',
      tenantId: TENANTS.A.id,
      host: HOST,
      services: ['SVC-SAMPLE-1'],
      sub: SUB,
      device: DEVICE,
      backendToken: TOKEN,
      // The session ends to the second, as the sessionEnd rule gives it (an ISO instant with .000).
      expiresAt: '2026-10-30T12:00:00.000Z',
    });
  });

  it('is null when the answer names no tenant, or a tenant that is not a tenant id', () => {
    const withoutTenant = answer();
    delete withoutTenant.tenant;
    expect(reporterSessionFor(withoutTenant, input)).toBeNull();
    expect(reporterSessionFor(answer({ tenant: 'NOT A TENANT' }), input)).toBeNull();
    expect(reporterSessionFor(answer({ tenant: 42 }), input)).toBeNull();
  });

  it('is null when the request has no host, or the host is not a host', () => {
    expect(reporterSessionFor(answer(), { ...input, host: null })).toBeNull();
    expect(reporterSessionFor(answer(), { ...input, host: 'tenant-a.example.test/evil' })).toBeNull();
  });

  it('is null when the token cannot be read for a person, or the answer is not the sign-in answer', () => {
    expect(reporterSessionFor(answer({ token: 'not-a-token' }), input)).toBeNull();
    expect(reporterSessionFor(answer({ token: unsignedToken('', Date.parse(EXPIRES) / 1000) }), input)).toBeNull();
    expect(reporterSessionFor(answer({ token: 7 }), input)).toBeNull();
    expect(reporterSessionFor(answer({ role: 'advisor' }), input)).toBeNull();
    expect(reporterSessionFor(null, input)).toBeNull();
    expect(reporterSessionFor('a string', input)).toBeNull();
  });

  it('is null when the expiry is in the past, is not a date, or is more than twelve hours away', () => {
    expect(reporterSessionFor(answer({ expiresAt: '2026-10-30T09:59:00Z' }), input)).toBeNull();
    expect(reporterSessionFor(answer({ expiresAt: 'soon' }), input)).toBeNull();
    // A token that lasts two days, so the twelve-hour ceiling on the answer is the one under test.
    const longToken = unsignedToken(SUB, Date.parse('2026-11-01T12:00:00Z') / 1000);
    expect(reporterSessionFor(answer({ token: longToken, expiresAt: '2026-10-31T11:00:00Z' }), input)).toBeNull();
    expect(reporterSessionFor(answer({ token: longToken, expiresAt: '2026-10-30T21:59:00Z' }), input)).not.toBeNull();
  });

  it('never keeps a service the answer does not name, and keeps none when the registration is not given', () => {
    const session = reporterSessionFor(answer({ registrationId: undefined, serviceId: undefined, serviceName: undefined }), input);
    expect(session).not.toBeNull();
    expect(session?.services).toEqual([]);
  });
});
