import { NextResponse, type NextRequest } from 'next/server';
import { isSamePathOnly, rolesFor } from '@/lib/auth/access';
import { entraAuthorityOrigin } from '@/lib/auth/oidc';
import { operatorAccessFor } from '@/lib/operator/access';
import { operatorSessionFromRequest } from '@/lib/operator/session';
import { sessionFromRequest } from '@/lib/auth/session';
import { buildCsp, securityHeaders } from '@/lib/security/csp';

// Next 16 calls this file `proxy`; `middleware` is deprecated (DEC-210). It does two jobs, in this
// order, on every page request.
//
// 1. The role guard (W09). A path under a staff prefix needs a live session of an allowed role. The
//    role is read from the sealed session cookie and from nothing else, so no query string, header
//    or client-held value can raise it. No session (none, expired, not ours) goes to /sign-in with
//    the path to come back to; the wrong role is shown /forbidden. Paths that are not guarded are not
//    touched, and do not need the session secret. The BFF routes check the session and role again
//    themselves (lib/bff/handler.ts).
// 2. The content security policy and the security headers (S01). Every response, including the
//    redirect to sign-in and the 403 page, gets a fresh nonce, the policy and the headers. The nonce
//    reaches Next.js through the request's Content-Security-Policy header, which Next.js reads to
//    apply the nonce to its own scripts, and through x-nonce for the pages that want it. Any
//    Content-Security-Policy or x-nonce the caller sent is overwritten, never trusted.

const NO_STORE = 'no-store';
const SIGN_IN_PATH = '/sign-in';
const OPERATOR_SIGN_IN_PATH = '/operator/sign-in';

function newNonce(): string {
  return Buffer.from(crypto.randomUUID()).toString('base64');
}

type Decision =
  | { kind: 'pass'; guarded: boolean }
  | { kind: 'sign-in'; url: URL }
  | { kind: 'forbidden'; url: URL };

// The operator console (TEN-083) is another door: its pages are guarded by the OPERATOR session cookie and by
// nothing a tenant's person holds, and an operator's cookie opens no tenant page (the tenant guard below
// reads its own cookie only). A tenant's person on a console page is sent to the console's sign-in.
async function decideOperator(request: NextRequest, roles: readonly string[]): Promise<Decision> {
  const { pathname, search } = request.nextUrl;
  const session = await operatorSessionFromRequest(request);
  if (!session) {
    const signIn = new URL(OPERATOR_SIGN_IN_PATH, request.url);
    const back = `${pathname}${search}`;
    if (isSamePathOnly(back)) signIn.searchParams.set('next', back);
    return { kind: 'sign-in', url: signIn };
  }
  if (!roles.includes(session.role)) return { kind: 'forbidden', url: new URL('/forbidden', request.url) };
  return { kind: 'pass', guarded: true };
}

async function decide(request: NextRequest): Promise<Decision> {
  const { pathname, search } = request.nextUrl;
  const operator = operatorAccessFor(pathname);
  if (operator.kind === 'public') return { kind: 'pass', guarded: false };
  if (operator.kind === 'guarded') return decideOperator(request, operator.roles);
  const allowed = rolesFor(pathname);
  if (allowed === null) return { kind: 'pass', guarded: false };

  const session = await sessionFromRequest(request);
  if (!session) {
    const signIn = new URL('/sign-in', request.url);
    const back = `${pathname}${search}`;
    if (isSamePathOnly(back)) signIn.searchParams.set('next', back);
    return { kind: 'sign-in', url: signIn };
  }
  if (!allowed.includes(session.role)) {
    return { kind: 'forbidden', url: new URL('/forbidden', request.url) };
  }
  return { kind: 'pass', guarded: true };
}

export async function proxy(request: NextRequest): Promise<NextResponse> {
  const nonce = newNonce();
  // The sign-in page's form posts to our start route, which redirects to the provider; the browser
  // checks that redirect against this page's form-action. Exactly this path, no other, names it.
  const signInPage = request.nextUrl.pathname === SIGN_IN_PATH || (request.nextUrl.pathname === OPERATOR_SIGN_IN_PATH);
  const authority = signInPage ? entraAuthorityOrigin() : null;
  const policy = buildCsp(nonce, process.env.NODE_ENV === 'development', {
    formActionOrigins: authority === null ? [] : [authority],
  });

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set('x-nonce', nonce);
  requestHeaders.set('Content-Security-Policy', policy);

  const decision = await decide(request);
  let response: NextResponse;
  switch (decision.kind) {
    case 'sign-in':
      response = NextResponse.redirect(decision.url);
      break;
    case 'forbidden':
      response = NextResponse.rewrite(decision.url, {
        request: { headers: requestHeaders },
        status: 403,
      });
      break;
    case 'pass':
      response = NextResponse.next({ request: { headers: requestHeaders } });
      break;
  }

  response.headers.set('Content-Security-Policy', policy);
  for (const [name, value] of Object.entries(securityHeaders())) {
    response.headers.set(name, value);
  }
  // A signed-out person pressing Back must not be shown a guarded page from the cache.
  if (decision.kind !== 'pass' || decision.guarded) response.headers.set('Cache-Control', NO_STORE);
  return response;
}

export const config = {
  // Every page path, so a path written oddly still reaches the guard, which decides. Only the static
  // files Next serves are left out (they are not rendered per request, so they need no nonce).
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
