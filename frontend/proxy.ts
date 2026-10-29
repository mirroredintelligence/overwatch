// STUB (red commit): replaced in the implementation commit.
import type { NextRequest, NextResponse } from 'next/server';

export async function proxy(request: NextRequest): Promise<NextResponse | undefined> {
  void request;
  return undefined;
}

export const config = { matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'] };
