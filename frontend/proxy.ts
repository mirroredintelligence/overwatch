import { NextResponse, type NextRequest } from 'next/server';
import { isSamePathOnly, rolesFor } from '@/lib/auth/access';
import { sessionFromRequest } from '@/lib/auth/session';

// The role guard (W09). Next 16 calls this file `proxy`; `middleware` is deprecated (DEC-172).
//
// A path under a staff prefix needs a live session of an allowed role. The role is read from the
// sealed session cookie and from nothing else, so no query string, header or client-held value can
// raise it. No session (none, expired, not ours) goes to /sign-in with the path to come back to;
// the wrong role is shown /forbidden. Paths that are not guarded are not touched, and do not need
// the session secret. The BFF routes check the session and role again themselves (lib/bff/handler.ts).

const NO_STORE = 'no-store';

function withNoStore(response: NextResponse): NextResponse {
  // A signed-out person pressing Back must not be shown a page from the cache.
  response.headers.set('Cache-Control', NO_STORE);
  return response;
}

export async function proxy(request: NextRequest): Promise<NextResponse> {
  const { pathname, search } = request.nextUrl;
  const allowed = rolesFor(pathname);
  if (allowed === null) return NextResponse.next();

  const session = await sessionFromRequest(request);
  if (!session) {
    const signIn = new URL('/sign-in', request.url);
    const back = `${pathname}${search}`;
    if (isSamePathOnly(back)) signIn.searchParams.set('next', back);
    return withNoStore(NextResponse.redirect(signIn));
  }

  if (!allowed.includes(session.role)) {
    return withNoStore(NextResponse.rewrite(new URL('/forbidden', request.url), { status: 403 }));
  }
  return withNoStore(NextResponse.next());
}

export const config = {
  // Every page path, so a path written oddly still reaches the guard, which decides. Only the static
  // files Next serves are left out.
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
