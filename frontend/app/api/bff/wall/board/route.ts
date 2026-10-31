import { withBff } from '@/lib/bff/handler';
import { BOARD_ROLES } from '@/lib/board/read';
import { readWallBoard } from '@/lib/board/wall';

// What a wall screen shows (TEN-072): the setting the back end holds for the screen (its own board or a
// network's, and whether the network closed to it) and that board, in one answer. It takes no input: no
// tenant, scope or network comes from the URL, the query string, a header or a body, and the screen has
// no network id to give (`withBff` refuses a request that names one). The board is the one the session's
// back-end token is for. See lib/board/wall.ts.

const NO_STORE = { 'Cache-Control': 'no-store' };

const get = withBff(async (_request, session) => Response.json(await readWallBoard(session), { headers: NO_STORE }), { roles: [...BOARD_ROLES] });

// Route handlers receive a context this route does not use.
export const GET = (request: Request) => get(request, undefined);
