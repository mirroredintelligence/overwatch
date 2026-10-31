// Relays the back end's server-sent event stream to the browser (W06). The relay
// sits between two parties that should not have to trust each other: it forwards
// only the events the wall and the advisor screens use, only the three small
// fields they need, and nothing else the back end might add by mistake. Event
// names come from R06 (`board`) and from the W06 prompt (`board.updated`,
// `booking.updated`); see DEC-152.

export const RELAYED_EVENTS: readonly string[] = [
  'board',
  'board.updated',
  'booking.updated',
  'heartbeat',
  'board-whole',
];

/** Events that carry the time and nothing else: the stream's heartbeat and a whole-board change. */
const TIME_ONLY_EVENTS: readonly string[] = ['heartbeat', 'board-whole'];

const KEEP_ALIVE = ': keep-alive\n\n';
// A frame bigger than this is not a board event. The relay stops rather than buffer it.
const MAX_FRAME_CHARS = 16 * 1024;

const SERVICE_ID = /^[A-Za-z0-9.-]{1,64}$/;
const UTC_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|\+00:00)$/;
const KINDS: readonly string[] = ['capacity', 'status', 'booking'];

/** The data of an event, cut down to the fields the pages use, each checked. */
function sanitise(name: string, data: string): string {
  const kept: Record<string, string> = {};
  let parsed: unknown;
  try {
    parsed = JSON.parse(data);
  } catch {
    parsed = null;
  }
  if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) {
    const { serviceId, kind, changedAt } = parsed as Record<string, unknown>;
    const timeOnly = TIME_ONLY_EVENTS.includes(name);
    if (!timeOnly && typeof serviceId === 'string' && SERVICE_ID.test(serviceId)) kept.serviceId = serviceId;
    if (!timeOnly && typeof kind === 'string' && KINDS.includes(kind)) kept.kind = kind;
    if (typeof changedAt === 'string' && UTC_TIME.test(changedAt) && !Number.isNaN(Date.parse(changedAt))) {
      kept.changedAt = changedAt;
    }
  }
  return JSON.stringify(kept);
}

type Frame = { event: string | null; data: string[]; comment: boolean };

function dispatch(frame: Frame): string {
  if (frame.event === null && frame.data.length === 0) return frame.comment ? KEEP_ALIVE : '';
  const name = frame.event === null || frame.event === '' ? 'message' : frame.event;
  if (!RELAYED_EVENTS.includes(name)) return '';
  return `event: ${name}\ndata: ${sanitise(name, frame.data.join('\n'))}\n\n`;
}

/** Reads server-sent event text as it arrives, in pieces, and gives back the text to forward. */
class FrameReader {
  private buffer = '';
  private frame: Frame = { event: null, data: [], comment: false };
  private frameChars = 0;
  overflow = false;

  push(text: string): string {
    this.buffer += text;
    let out = '';
    for (;;) {
      const end = /\r\n|\n|\r/.exec(this.buffer);
      if (end === null) break;
      // A CR at the very end may be the first half of a CRLF: wait for the next piece.
      if (end[0] === '\r' && end.index + 1 === this.buffer.length) break;
      const line = this.buffer.slice(0, end.index);
      this.buffer = this.buffer.slice(end.index + end[0].length);
      out += this.line(line);
      if (this.overflow) return out;
    }
    if (this.buffer.length > MAX_FRAME_CHARS) this.overflow = true;
    return out;
  }

  /** The stream ended: a CR at the very end was a line end after all. */
  flush(): string {
    return this.buffer.endsWith('\r') ? this.push('\n') : '';
  }

  private line(line: string): string {
    if (line === '') {
      const out = dispatch(this.frame);
      this.frame = { event: null, data: [], comment: false };
      this.frameChars = 0;
      return out;
    }
    this.frameChars += line.length;
    if (this.frameChars > MAX_FRAME_CHARS) {
      this.overflow = true;
      return '';
    }
    if (line.startsWith(':')) {
      this.frame.comment = true;
      return '';
    }
    const colon = line.indexOf(':');
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    if (field === 'event') this.frame.event = value;
    else if (field === 'data') this.frame.data.push(value);
    // `id` and `retry` are never forwarded: they could change how the browser reconnects.
    return '';
  }
}

export type RelayOptions = {
  /** When this aborts, the upstream is cancelled and the relayed stream ends. */
  signal?: AbortSignal;
  /** Called when the reader of the relayed stream goes away (cancels it). */
  onCancel?: () => void;
};

export function relayEvents(
  upstream: ReadableStream<Uint8Array>,
  options: RelayOptions = {},
): ReadableStream<Uint8Array> {
  const reader = upstream.getReader();
  const decoder = new TextDecoder();
  const encoder = new TextEncoder();
  const frames = new FrameReader();
  const stop = () => void reader.cancel().catch(() => undefined);
  options.signal?.addEventListener('abort', stop, { once: true });
  if (options.signal?.aborted) stop();

  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      for (;;) {
        let chunk: ReadableStreamReadResult<Uint8Array>;
        try {
          chunk = await reader.read();
        } catch {
          // The back end connection failed: end the stream, so the browser reconnects.
          controller.close();
          return;
        }
        if (chunk.done) {
          const rest = frames.flush();
          if (rest !== '') controller.enqueue(encoder.encode(rest));
          controller.close();
          return;
        }
        const out = frames.push(decoder.decode(chunk.value, { stream: true }));
        if (out !== '') controller.enqueue(encoder.encode(out));
        if (frames.overflow) {
          stop();
          controller.close();
          return;
        }
        if (out !== '') return;
      }
    },
    cancel(reason) {
      options.signal?.removeEventListener('abort', stop);
      options.onCancel?.();
      // The browser has gone. Close the back end connection, without waiting for it to confirm.
      void reader.cancel(reason).catch(() => undefined);
    },
  });
}
