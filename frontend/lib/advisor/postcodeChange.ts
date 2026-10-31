import { bffFetch, newIdempotencyKey } from './browser';
import type { CaseInput, CaseView } from './codes';
import { normalisePostcode } from './postcode';

// The browser's call that changes the case's postcode from the "postcode not found" state (MapWeb 3). It
// is the needs form's save (PUT the case with the ETag that was read), with the coded fields as they are
// and only the postcode new. The postcode goes to the case save and nowhere else: never a URL, never
// browser storage (DEC-398).

export type PostcodeChange = 'saved' | 'invalid' | 'conflict' | 'failed';

/** True when the case read has every coded part the save needs, so the postcode alone can change. */
export function canChangePostcode(view: CaseView | null): boolean {
  return (
    view !== null &&
    !view.closed &&
    view.referrerType !== null &&
    view.ageBand !== null &&
    view.urgency !== null &&
    view.needs.length > 0 &&
    view.etag !== null
  );
}

export async function changePostcode(view: CaseView, typed: string): Promise<PostcodeChange> {
  const postcode = normalisePostcode(typed);
  if (postcode === null) return 'invalid';
  if (!canChangePostcode(view) || view.referrerType === null || view.ageBand === null || view.urgency === null) {
    return 'failed';
  }
  const input: CaseInput = {
    referrerType: view.referrerType,
    ageBand: view.ageBand,
    postcode,
    needs: view.needs,
    urgency: view.urgency,
    scores: view.scores,
  };
  const reply = await bffFetch(`/api/bff/cases/${encodeURIComponent(view.id)}`, {
    method: 'PUT',
    body: input,
    idempotencyKey: newIdempotencyKey(),
    ifMatch: view.etag ?? undefined,
  });
  if (reply.ok) return 'saved';
  return reply.status === 412 ? 'conflict' : 'failed';
}
