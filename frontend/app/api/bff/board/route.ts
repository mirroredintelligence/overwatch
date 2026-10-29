import { withBff } from '@/lib/bff/handler';
import { BOARD_ROLES, readBoard } from '@/lib/board/read';

// The browser's read of the wall board. It takes no input: no tenant, scope or
// organisation comes from the URL, the query string, a header or a body. The
// board is the one the session's back-end token is for.

const NO_STORE = { 'Cache-Control': 'no-store' };

const get = withBff(
  async (_request, session) => Response.json(await readBoard(session), { headers: NO_STORE }),
  { roles: [...BOARD_ROLES] },
);

// Route handlers receive a context this route does not use.
export const GET = (request: Request) => get(request, undefined);
