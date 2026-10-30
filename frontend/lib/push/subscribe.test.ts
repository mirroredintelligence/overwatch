import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { subscribeToPush } from './subscribe';

const subscribe = vi.fn();
const registration = { pushManager: { subscribe } } as unknown as ServiceWorkerRegistration;

beforeEach(() => subscribe.mockReset());
afterEach(() => vi.restoreAllMocks());

describe('subscribeToPush', () => {
  it('subscribes with user-visible messages and the application server key', async () => {
    subscribe.mockResolvedValue({ endpoint: 'https://push.example/x', toJSON: () => ({ endpoint: 'https://push.example/x', keys: { p256dh: 'p', auth: 'a' } }) });
    const subscription = await subscribeToPush(registration, 'BPublicKeyValue');
    expect(subscribe).toHaveBeenCalledWith(
      expect.objectContaining({ userVisibleOnly: true, applicationServerKey: expect.any(Uint8Array) }),
    );
    expect(subscription).toEqual({ endpoint: 'https://push.example/x', keys: { p256dh: 'p', auth: 'a' } });
  });
});
