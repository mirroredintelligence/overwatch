import { withBff } from '@/lib/bff/handler';
import { notBuilt } from '@/lib/reporter/bff';

// GET /api/bff/reporter/settings (W37). The back end has no reporter settings route yet: not-built.
export const GET = withBff(() => notBuilt(), { roles: ['reporter'] });
