import { withBff } from '@/lib/bff/handler';
import { notBuilt } from '@/lib/reporter/bff';

// GET /api/bff/reporter/bookings/[ref] (W36). The back end's Task read answers the reporter with a
// FHIR projection, and the reference-to-Task mapping is not built: not-built until it is.
export const GET = withBff(() => notBuilt(), { roles: ['reporter'] });
