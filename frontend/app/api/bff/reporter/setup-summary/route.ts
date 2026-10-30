import { withBff } from '@/lib/bff/handler';
import { notBuilt } from '@/lib/reporter/bff';

// GET /api/bff/reporter/setup-summary (W34). The back end has no reporter summary route yet.
export const GET = withBff(() => notBuilt(), { roles: ['reporter'] });
