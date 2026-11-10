// The byte range of the map's tile file that a browser asks for (DEC-1362). PMTiles is read with HTTP range
// requests, so the route takes one `Range: bytes=a-b` and nothing else; a larger or odd range is refused so the
// route cannot be used to pull the whole file.

export const MAX_RANGE_BYTES = 4 * 1024 * 1024;

export type ByteRange = { start: number; end: number };

/** `bytes=<start>-<end>` with both ends, in order, no longer than MAX_RANGE_BYTES; anything else is null. */
export function parseRange(header: string | null): ByteRange | null {
  if (header === null) return null;
  const match = /^bytes=(\d{1,13})-(\d{1,13})$/.exec(header.trim());
  if (match === null) return null;
  const start = Number(match[1]);
  const end = Number(match[2]);
  if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || end < start) return null;
  if (end - start + 1 > MAX_RANGE_BYTES) return null;
  return { start, end };
}
