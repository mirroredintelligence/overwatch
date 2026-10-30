import { notBuilt, preSession } from '@/lib/reporter/bff';

// POST /api/bff/identity/code (W33, W37). The back end's code route takes a mobile number, which the
// browser never holds: an invitation's number is only masked. Until the back end resolves an
// invitation or a device to its number, this answers not-built. No body field is read or echoed.
export const POST = preSession(() => notBuilt());
