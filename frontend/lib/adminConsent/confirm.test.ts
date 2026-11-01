// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';

const callBackend = vi.fn();
vi.mock('@/lib/fhir/hostCall', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/fhir/hostCall')>()),
  callBackend: (...args: unknown[]) => callBackend(...args),
}));

import { BackendCallError } from '@/lib/fhir/hostCall';
import { confirmConsent, saidByRedirect } from './confirm';

const STATE = `new-org.${'A'.repeat(43)}`;
const HOST = 'overwatch.example.test';

beforeEach(() => callBackend.mockReset());

describe('what the redirect said', () => {
  it('reads only Microsoft’s own True and False', () => {
    expect(saidByRedirect('True')).toBe(true);
    expect(saidByRedirect('false')).toBe(false);
    expect(saidByRedirect('yes')).toBeUndefined();
    expect(saidByRedirect(undefined)).toBeUndefined();
  });
});

describe('confirming the consent', () => {
  it('asks the back end with the state and what the redirect said, and never a tenant', async () => {
    callBackend.mockResolvedValue({ status: 200, body: { status: 'consented', reason: null, organisation: 'Sample Organisation' } });
    const outcome = await confirmConsent({ state: STATE, adminConsent: 'True', host: HOST });

    expect(outcome).toEqual({ kind: 'consented', organisation: 'Sample Organisation' });
    expect(callBackend).toHaveBeenCalledWith({ method: 'POST', path: '/admin-consent/confirmation', host: HOST, body: { state: STATE, adminConsent: true } });
  });

  it('is not proof that the redirect said yes: a pending answer stays pending, with its reason', async () => {
    callBackend.mockResolvedValue({ status: 200, body: { status: 'pending', reason: 'Overwatch is not installed in your directory yet.', organisation: 'Org' } });
    expect(await confirmConsent({ state: STATE, adminConsent: 'True', host: HOST })).toEqual({
      kind: 'pending',
      reason: 'Overwatch is not installed in your directory yet.',
      organisation: 'Org',
    });
  });

  it('leaves the flag out when the redirect did not say True or False', async () => {
    callBackend.mockResolvedValue({ status: 200, body: { status: 'expired', reason: null, organisation: null } });
    const outcome = await confirmConsent({ state: STATE, adminConsent: undefined, host: HOST });
    expect(outcome.kind).toBe('expired');
    expect(callBackend.mock.calls[0]?.[0].body).toEqual({ state: STATE });
  });

  it.each([undefined, '', 'not-a-state', 'NEW.abc', `new-org.${'A'.repeat(42)}`, `new-org.${'A'.repeat(44)}`, `../x.${'A'.repeat(43)}`])('makes no call for state %j', async (state) => {
    expect(await confirmConsent({ state, adminConsent: 'True', host: HOST })).toEqual({ kind: 'invalid' });
    expect(callBackend).not.toHaveBeenCalled();
  });

  it('answers invalid for a 404, whatever the reason', async () => {
    callBackend.mockResolvedValue({ status: 404, body: { resourceType: 'OperationOutcome' } });
    expect(await confirmConsent({ state: STATE, adminConsent: 'True', host: HOST })).toEqual({ kind: 'invalid' });
  });

  it.each([429, 500, 502])('answers unavailable for a %s, and for a body that is not the one expected', async (status) => {
    callBackend.mockResolvedValue({ status, body: undefined });
    expect(await confirmConsent({ state: STATE, adminConsent: 'True', host: HOST })).toEqual({ kind: 'unavailable' });
    callBackend.mockResolvedValue({ status: 200, body: { status: 'something-new' } });
    expect(await confirmConsent({ state: STATE, adminConsent: 'True', host: HOST })).toEqual({ kind: 'unavailable' });
    callBackend.mockResolvedValue({ status: 200, body: { status: 'pending', reason: null } });
    expect(await confirmConsent({ state: STATE, adminConsent: 'True', host: HOST })).toEqual({ kind: 'unavailable' });
  });

  it('answers unavailable when the back end cannot be reached', async () => {
    const down = async (): Promise<never> => {
      throw new BackendCallError('unavailable');
    };
    expect(await confirmConsent({ state: STATE, adminConsent: 'True', host: HOST }, down)).toEqual({ kind: 'unavailable' });
  });
});
