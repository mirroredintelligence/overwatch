import { bffFetch, newIdempotencyKey } from './browser';

// The browser's call that keeps a district the advisor chose on its own (W50, W9H DEC-1045). The BFF reads
// the case for its ETag and saves the district; nothing here holds a postcode or a case's details, and the
// key is made for this press, so a double press is one write.

/** True when the district was kept on the case. */
export async function chooseDistrict(caseId: string, district: string): Promise<boolean> {
  const reply = await bffFetch(`/api/bff/cases/${encodeURIComponent(caseId)}/district`, {
    method: 'PUT',
    body: { district },
    idempotencyKey: newIdempotencyKey(),
  });
  return reply.ok;
}
