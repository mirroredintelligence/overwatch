import { notBuilt, preSession } from '@/lib/reporter/bff';

// POST /api/bff/identity/code/verify (W33). Same gap as the code route: the back end needs the
// mobile number and device id, and the body's own fields (a tenant, a number) are never trusted.
// Until the back end can take an invitation, this answers not-built.
export const POST = preSession(() => notBuilt());
