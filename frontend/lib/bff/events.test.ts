// @vitest-environment node
import { describe, expect, it, vi } from 'vitest';
import { frame, readAll, streamOf } from '@/test/sse';
import { RELAYED_EVENTS, relayEvents } from './events';

// The relay sits between the back end's event stream and the browser. It forwards
// only the events the wall and the advisor screens use, only the fields they need,
// and nothing the back end might add by mistake.

async function relay(...chunks: string[]): Promise<string> {
  return readAll(relayEvents(streamOf(chunks)));
}

const SERVICE = '{"serviceId":"svc-ucr-west","changedAt":"2026-10-23T13:12:00Z"}';

describe('relayEvents: which events', () => {
  it('relays exactly board (the back end event), board.updated and booking.updated', () => {
    expect([...RELAYED_EVENTS].sort()).toEqual(['board', 'board-whole', 'board.updated', 'booking.updated', 'heartbeat']);
  });

  it.each(['board', 'board.updated', 'booking.updated'])('forwards a %s event', async (name) => {
    expect(await relay(frame(name, SERVICE))).toBe(`event: ${name}\ndata: ${SERVICE}\n\n`);
  });

  it.each(['error', 'message', 'Board', 'BOARD', 'board-updated', 'board.updated ', 'boards', 'ping', '__proto__', ''])(
    'drops an event named %j',
    async (name) => {
      expect(await relay(frame(name, SERVICE))).toBe('');
    },
  );

  it('drops an event with no name at all (the browser would deliver it as a message)', async () => {
    expect(await relay(frame(null, SERVICE))).toBe('');
  });

  it('forwards the allowed events and drops the others between them, in order', async () => {
    const text = await relay(frame('board', SERVICE), frame('secret', '{"x":1}'), frame('booking.updated', SERVICE));

    expect(text).toBe(`event: board\ndata: ${SERVICE}\n\nevent: booking.updated\ndata: ${SERVICE}\n\n`);
  });
});

describe('relayEvents: what is in an event', () => {
  it('keeps only serviceId, kind and changedAt', async () => {
    const data = JSON.stringify({
      serviceId: 'svc-1',
      kind: 'capacity',
      changedAt: '2026-10-23T13:12:00Z',
      patientName: 'Not for the wall',
      comment: 'free text',
    });

    const text = await relay(frame('board', data));

    expect(text).toBe('event: board\ndata: {"serviceId":"svc-1","kind":"capacity","changedAt":"2026-10-23T13:12:00Z"}\n\n');
    expect(text).not.toContain('Not for the wall');
    expect(text).not.toContain('free text');
  });

  it('drops a field of the wrong shape: a service id with other characters, an unknown kind, a time that is not a UTC instant', async () => {
    const data = JSON.stringify({ serviceId: 'a b/../c', kind: 'delete-everything', changedAt: 'tomorrow' });

    expect(await relay(frame('board', data))).toBe('event: board\ndata: {}\n\n');
  });

  it('drops a service id that is too long, and one that is not text', async () => {
    expect(await relay(frame('board', JSON.stringify({ serviceId: 'a'.repeat(65) })))).toBe('event: board\ndata: {}\n\n');
    expect(await relay(frame('board', JSON.stringify({ serviceId: 7 })))).toBe('event: board\ndata: {}\n\n');
    expect(await relay(frame('board', JSON.stringify({ serviceId: 'a'.repeat(64) })))).toContain('a'.repeat(64));
  });

  it('still forwards the event, with empty data, when the data is not JSON or not an object, so the page still refreshes', async () => {
    for (const data of ['not json', '[1,2]', '"text"', '7', 'null', '']) {
      expect(await relay(frame('board', data))).toBe('event: board\ndata: {}\n\n');
    }
  });

  it('joins a data field sent over several lines before reading it', async () => {
    const text = await relay('event: board\ndata: {"serviceId":\ndata: "svc-1"}\n\n');

    expect(text).toBe('event: board\ndata: {"serviceId":"svc-1"}\n\n');
  });

  it('does not forward id or retry lines, which could change how the browser reconnects', async () => {
    const text = await relay('id: 7\nretry: 1\nevent: board\ndata: {"serviceId":"s1"}\n\n');

    expect(text).toBe('event: board\ndata: {"serviceId":"s1"}\n\n');
  });

  it('does not forward the text of a comment, only a fixed keep-alive comment', async () => {
    const text = await relay(': secret comment text\n\n');

    expect(text).toBe(': keep-alive\n\n');
    expect(text).not.toContain('secret');
  });

  it('forwards the heartbeat and the whole-board event with the time only (KI-54, KI-55)', async () => {
    const data = JSON.stringify({ changedAt: '2026-10-23T13:12:00Z', serviceId: 'svc-1', note: 'Jane Smith' });

    expect(await relay(frame('heartbeat', data))).toBe('event: heartbeat\ndata: {"changedAt":"2026-10-23T13:12:00Z"}\n\n');
    expect(await relay(frame('board-whole', data))).toBe('event: board-whole\ndata: {"changedAt":"2026-10-23T13:12:00Z"}\n\n');
  });

  it('forwards a heartbeat whose data is bad as an empty one, so the page still hears the beat', async () => {
    expect(await relay(frame('heartbeat', 'not json'))).toBe('event: heartbeat\ndata: {}\n\n');
  });

  it('survives text in a dropped field that is not ASCII', async () => {
    const text = await relay(frame('board', JSON.stringify({ serviceId: 'svc-1', note: 'café \u{1F600}' })));

    expect(text).toBe('event: board\ndata: {"serviceId":"svc-1"}\n\n');
  });
});

describe('relayEvents: how the bytes arrive', () => {
  it('reads a frame split across chunks, in the middle of a field name and of a value', async () => {
    const whole = frame('board', SERVICE);
    for (let cut = 1; cut < whole.length; cut += 7) {
      expect(await relay(whole.slice(0, cut), whole.slice(cut))).toBe(`event: board\ndata: ${SERVICE}\n\n`);
    }
  });

  it('reads CRLF and bare CR line ends', async () => {
    expect(await relay(`event: board\r\ndata: ${SERVICE}\r\n\r\n`)).toBe(`event: board\ndata: ${SERVICE}\n\n`);
    expect(await relay(`event: board\rdata: ${SERVICE}\r\r`)).toBe(`event: board\ndata: ${SERVICE}\n\n`);
  });

  it('reads CRLF line ends split between the CR and the LF at every position', async () => {
    const whole = `event: board\r\ndata: ${SERVICE}\r\n\r\n`;
    for (let cut = 1; cut < whole.length; cut += 1) {
      expect(await relay(whole.slice(0, cut), whole.slice(cut))).toBe(`event: board\ndata: ${SERVICE}\n\n`);
    }
  });

  it('reads a multi-byte character split across two chunks', async () => {
    const bytes = new TextEncoder().encode(frame('board', JSON.stringify({ serviceId: 'svc-1', note: 'é' })));
    const cut = bytes.indexOf(0xc3) + 1;

    const text = await readAll(relayEvents(streamOf([bytes.slice(0, cut), bytes.slice(cut)])));

    expect(text).toBe('event: board\ndata: {"serviceId":"svc-1"}\n\n');
  });

  it('does not forward a frame that never ended', async () => {
    expect(await relay('event: board\ndata: {"serviceId":"s1"}\n')).toBe('');
  });

  it('closes, forwarding nothing more, when one frame grows past 16 KiB', async () => {
    const huge = `event: board\ndata: ${'x'.repeat(20_000)}`;

    const text = await relay(frame('board', SERVICE), huge, frame('board', SERVICE));

    expect(text).toBe(`event: board\ndata: ${SERVICE}\n\n`);
  });

  it('closes, forwarding nothing more, when one frame is made of many short lines that add up past 16 KiB', async () => {
    const lines = Array.from({ length: 400 }, () => `data: ${'x'.repeat(60)}\n`).join('');

    const text = await relay(frame('board', SERVICE), `event: board\n${lines}`, '\n', frame('board', SERVICE));

    expect(text).toBe(`event: board\ndata: ${SERVICE}\n\n`);
  });

  it('closes cleanly when the upstream fails', async () => {
    const failing = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(frame('board', SERVICE)));
      },
      pull() {
        throw new Error('connection reset');
      },
    });

    expect(await readAll(relayEvents(failing))).toBe(`event: board\ndata: ${SERVICE}\n\n`);
  });

  it('cancels the upstream when the browser side is cancelled', async () => {
    const onCancel = vi.fn();
    const out = relayEvents(streamOf([frame('board', SERVICE)], { hold: true, onCancel }));
    const reader = out.getReader();
    await reader.read();

    await reader.cancel();

    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('delivers a frame as soon as it is complete, without waiting for the stream to end', async () => {
    const out = relayEvents(streamOf([frame('board', SERVICE)], { hold: true }));
    const reader = out.getReader();

    const first = await Promise.race([
      reader.read(),
      new Promise<'waited'>((resolve) => setTimeout(() => resolve('waited'), 500)),
    ]);

    expect(first).not.toBe('waited');
    await reader.cancel();
  });

  it('calls onCancel when the browser side goes away', async () => {
    const onCancel = vi.fn();
    const out = relayEvents(streamOf([frame('board', SERVICE)], { hold: true }), { onCancel });
    const reader = out.getReader();
    await reader.read();

    await reader.cancel();

    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('ends the relayed stream and cancels the upstream when its signal aborts', async () => {
    const onCancel = vi.fn();
    const controller = new AbortController();
    const out = relayEvents(streamOf([frame('board', SERVICE)], { hold: true, onCancel }), { signal: controller.signal });
    const reader = out.getReader();
    await reader.read();

    controller.abort();

    await expect(reader.read()).resolves.toMatchObject({ done: true });
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('is already closed when the signal was aborted before it started', async () => {
    const onCancel = vi.fn();
    const controller = new AbortController();
    controller.abort();

    const text = await readAll(relayEvents(streamOf([frame('board', SERVICE)], { hold: true, onCancel }), { signal: controller.signal }));

    expect(text).toBe('');
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
