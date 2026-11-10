import { open } from 'node:fs/promises';
import type { ByteRange } from './range';

// Where the tile file is read from (DEC-1362): the private blob in the map-data container, with the web app's
// managed identity (`OVERWATCH_MAP_TILES_URL`), or a local file for development (`OVERWATCH_MAP_TILES_FILE`).
// Neither set: the map has no tiles and the pages keep the schematic.

type Env = Record<string, string | undefined>;

export type TileBytes = { status: 206 | 404 | 502; body: Uint8Array | null; total: number | null };

const STORAGE_SCOPE = 'https://storage.azure.com/.default';
const STORAGE_VERSION = '2023-11-03';

type Token = { token: string; expiresOnTimestamp: number };
let credential: { getToken(scope: string): Promise<Token | null> } | null = null;

async function bearer(): Promise<string> {
  if (credential === null) {
    const { DefaultAzureCredential } = await import('@azure/identity');
    credential = new DefaultAzureCredential();
  }
  const token = await credential.getToken(STORAGE_SCOPE);
  if (token === null) throw new Error('no storage token');
  return token.token;
}

export function tilesConfigured(env: Env = process.env): boolean {
  return Boolean(env.OVERWATCH_MAP_TILES_URL) || Boolean(env.OVERWATCH_MAP_TILES_FILE);
}

async function fromFile(path: string, range: ByteRange): Promise<TileBytes> {
  const handle = await open(path, 'r');
  try {
    const { size } = await handle.stat();
    if (range.start >= size) return { status: 404, body: null, total: size };
    const end = Math.min(range.end, size - 1);
    const buffer = new Uint8Array(end - range.start + 1);
    await handle.read(buffer, 0, buffer.length, range.start);
    return { status: 206, body: buffer, total: size };
  } finally {
    await handle.close();
  }
}

async function fromBlob(url: string, range: ByteRange): Promise<TileBytes> {
  const response = await fetch(url, {
    headers: {
      Authorization: `Bearer ${await bearer()}`,
      'x-ms-version': STORAGE_VERSION,
      Range: `bytes=${range.start}-${range.end}`,
    },
    cache: 'no-store',
  });
  if (response.status === 416 || response.status === 404) return { status: 404, body: null, total: null };
  if (response.status !== 206 && response.status !== 200) return { status: 502, body: null, total: null };
  const total = Number(/\/(\d+)$/.exec(response.headers.get('Content-Range') ?? '')?.[1] ?? NaN);
  return { status: 206, body: new Uint8Array(await response.arrayBuffer()), total: Number.isFinite(total) ? total : null };
}

export async function readTileRange(range: ByteRange, env: Env = process.env): Promise<TileBytes> {
  const file = env.OVERWATCH_MAP_TILES_FILE;
  if (file) return fromFile(file, range);
  const url = env.OVERWATCH_MAP_TILES_URL;
  if (url) return fromBlob(url, range);
  return { status: 404, body: null, total: null };
}
