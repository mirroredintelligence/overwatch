// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { frame, readAll, streamOf } from '@/test/sse';
import { NETWORK_RELAYED_EVENTS, relayEvents } from './events';

// TEN-068: the network stream relay. The network channel carries `network-board` (the time of a
// change, nothing else) and `scope-ended` (the viewer is no longer allowed). The relay forwards those
// two only, cut down to the one field, and never the tenant board's events on this stream, or the
// network's on the tenant stream.

async function relay(...chunks: string[]): Promise<string> {
  return readAll(relayEvents(streamOf(chunks), { events: 'network' }));
}

const CHANGED = '{"changedAt":"2026-10-23T13:12:00+00:00"}';

describe('relayEvents for the network stream', () => {
  it('relays exactly network-board and scope-ended', () => {
    expect([...NETWORK_RELAYED_EVENTS].sort()).toEqual(['network-board', 'scope-ended']);
  });

  it('forwards a network-board event with its time', async () => {
    expect(await relay(frame('network-board', CHANGED))).toBe(`event: network-board\ndata: ${CHANGED}\n\n`);
  });

  it('forwards scope-ended with no data of the back end', async () => {
    expect(await relay(frame('scope-ended', '{"reason":"x","tenant":"trust-b"}'))).toBe('event: scope-ended\ndata: {}\n\n');
  });

  it('drops the tenant board events and anything else', async () => {
    const text = await relay(frame('board', CHANGED), frame('board.updated', CHANGED), frame('booking.updated', CHANGED), frame('secret', '{}'), frame(null, '{}'));
    expect(text).toBe('');
  });

  it('keeps only changedAt, and only a UTC time', async () => {
    const data = JSON.stringify({ changedAt: '2026-10-23T13:12:00+00:00', networkId: 'net-sample', tenantId: 'trust-b', serviceId: 'svc-1' });
    expect(await relay(frame('network-board', data))).toBe(`event: network-board\ndata: ${CHANGED}\n\n`);
    expect(await relay(frame('network-board', '{"changedAt":"yesterday"}'))).toBe('event: network-board\ndata: {}\n\n');
    expect(await relay(frame('network-board', 'not json'))).toBe('event: network-board\ndata: {}\n\n');
  });

  it('forwards a keep-alive comment as the fixed comment, not the back end text', async () => {
    expect(await relay(': 10.0.0.5 internal\n\n')).toBe(': keep-alive\n\n');
  });

  it('is not what the tenant stream relays: the default stays the three tenant events', async () => {
    expect(await readAll(relayEvents(streamOf([frame('network-board', CHANGED)])))).toBe('');
  });
});
