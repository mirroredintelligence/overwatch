// Stub for the red commit (DEC-010): the per-request nonce and headers (S01).
import type { NextRequest } from 'next/server';

export function proxy(request: NextRequest): Response {
  throw new Error(`S01: proxy is not built yet (${request.url})`);
}

export const config = { matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'] };
