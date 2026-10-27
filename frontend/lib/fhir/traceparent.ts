// W3C Trace Context traceparent: version 00, a 16-byte trace id, an 8-byte
// parent id and the sampled flag. https://www.w3.org/TR/trace-context/
const SAMPLED = '01';

function randomHex(bytes: number): string {
  const buffer = new Uint8Array(bytes);
  crypto.getRandomValues(buffer);
  return Array.from(buffer, (byte) => byte.toString(16).padStart(2, '0')).join('');
}

export function newTraceparent(): string {
  // The trace id must not be all zeros. Draw again in the (practically
  // impossible) case that it is, rather than send an invalid header.
  let traceId = randomHex(16);
  while (/^0+$/.test(traceId)) {
    traceId = randomHex(16);
  }
  return `00-${traceId}-${randomHex(8)}-${SAMPLED}`;
}
