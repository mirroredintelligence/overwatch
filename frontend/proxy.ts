// Next.js 16 calls the middleware file `proxy.ts` (middleware.ts is deprecated; see the
// Next.js docs in node_modules/next/dist/docs). Every page response gets a fresh nonce, the policy
// and the security headers (S01). The nonce reaches Next.js through the request's
// Content-Security-Policy header, which Next.js reads to apply the nonce to its own scripts, and
// through x-nonce for the pages that want it.
import { type NextRequest, NextResponse } from 'next/server';
import { buildCsp, securityHeaders } from '@/lib/security/csp';

function newNonce(): string {
  return Buffer.from(crypto.randomUUID()).toString('base64');
}

export function proxy(request: NextRequest): NextResponse {
  const nonce = newNonce();
  const policy = buildCsp(nonce, process.env.NODE_ENV === 'development');

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set('x-nonce', nonce);
  requestHeaders.set('Content-Security-Policy', policy);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set('Content-Security-Policy', policy);
  for (const [name, value] of Object.entries(securityHeaders())) {
    response.headers.set(name, value);
  }
  return response;
}

// Static build assets are not rendered per request, so they need no nonce and are left out.
export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
