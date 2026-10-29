// Relays the back end's event stream to the browser (W06).
export const RELAYED_EVENTS: readonly string[] = [];

export function relayEvents(upstream: ReadableStream<Uint8Array>): ReadableStream<Uint8Array> {
  return upstream;
}
