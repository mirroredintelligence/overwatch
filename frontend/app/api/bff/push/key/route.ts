import { notBuilt } from '@/lib/reporter/bff';

// GET /api/bff/push/key (W34). The public key for the push subscription. No back-end route serves
// it yet, so this answers not-built and the all-set page says the save did not happen.
export function GET(): Response {
  return notBuilt();
}
