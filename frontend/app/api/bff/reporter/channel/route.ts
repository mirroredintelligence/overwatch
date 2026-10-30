import { withBff } from '@/lib/bff/handler';
import { notBuilt } from '@/lib/reporter/bff';

// POST /api/bff/reporter/channel (W33, W37). A reporter's session and CSRF are checked by withBff.
// The back end has no reporter channel route yet, so this answers not-built.
export const POST = withBff(() => notBuilt(), { roles: ['reporter'] });
