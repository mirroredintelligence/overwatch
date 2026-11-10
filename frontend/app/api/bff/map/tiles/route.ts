import { withBff } from '@/lib/bff/handler';
import { parseRange } from '@/lib/map/tiles/range';
import { readTileRange, tilesConfigured } from '@/lib/map/tiles/source';

// The map's tiles (DEC-1362): one byte range of the PMTiles file that holds OS Open Zoomstack, read from the
// private blob with the app's own identity and passed on. The browser only ever talks to this origin, so the
// CSP stays `connect-src 'self'` and the storage account stays private. Any signed-in person, since the map is
// for advisors, leads and screens alike; the file holds public map data and nothing about a patient, and the
// range asked for names no place a person is looking at beyond the tile coordinates the browser would
// ask any tile server for, which here only this app sees.

const get = withBff(async (request) => {
  if (!tilesConfigured()) return Response.json({ code: 'no-tiles' }, { status: 404 });
  const range = parseRange(request.headers.get('Range'));
  if (range === null) return Response.json({ code: 'invalid' }, { status: 416 });
  let bytes;
  try {
    bytes = await readTileRange(range);
  } catch {
    return Response.json({ code: 'tiles-unavailable' }, { status: 502 });
  }
  if (bytes.status !== 206 || bytes.body === null) return Response.json({ code: bytes.status === 404 ? 'no-tiles' : 'tiles-unavailable' }, { status: bytes.status });
  const end = range.start + bytes.body.length - 1;
  return new Response(Buffer.from(bytes.body), {
    status: 206,
    headers: {
      'Content-Type': 'application/octet-stream',
      'Content-Range': `bytes ${range.start}-${end}/${bytes.total ?? '*'}`,
      'Accept-Ranges': 'bytes',
    },
  });
});

export const GET = (request: Request) => get(request, undefined);
