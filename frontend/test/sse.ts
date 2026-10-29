// Helpers for the server-sent-event tests (W06).

const encoder = new TextEncoder();
const decoder = new TextDecoder();

/** A stream that delivers each chunk in turn, then ends (or stays open when `hold` is set). */
export function streamOf(chunks: (string | Uint8Array)[], options: { hold?: boolean; onCancel?: () => void } = {}) {
  let index = 0;
  return new ReadableStream<Uint8Array>({
    pull(controller) {
      if (index < chunks.length) {
        const chunk = chunks[index++];
        controller.enqueue(typeof chunk === 'string' ? encoder.encode(chunk) : chunk);
      } else if (!options.hold) {
        controller.close();
      }
      // When held, pull is not called again until there is room, so the stream stays open and idle.
    },
    cancel() {
      options.onCancel?.();
    },
  });
}

/** Reads a whole stream as text. */
export async function readAll(stream: ReadableStream<Uint8Array>): Promise<string> {
  const reader = stream.getReader();
  let text = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return text + decoder.decode();
    text += decoder.decode(value, { stream: true });
  }
}

export function frame(event: string | null, data: string): string {
  return `${event === null ? '' : `event: ${event}\n`}data: ${data}\n\n`;
}
