import { whenText } from '@/lib/tenantAdmin/words';
import type { GrantRow, ListingReason, ListingStatus, MemberStatus, Scope } from './views';

// The words the network administration and sharing screens print for what the back end names in codes
// (docs/design/network-ui.md sections 7 and 8). Pure text: no tenant, nothing clinical, no name of a place.
// A code this module does not know is printed as it is, never guessed at. Times are London time.

export { whenText };

const date = new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/London', day: 'numeric', month: 'short', year: 'numeric' });

/** "21 Oct 2026" in London time, or a dash for no time. */
export function dateText(iso: string | null | undefined): string {
  if (iso === null || iso === undefined) return '-';
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? '-' : date.format(parsed);
}

export const SCOPE_WORD: Readonly<Record<Scope, string>> = { capacity: 'Capacity', directory: 'Directory', criteria: 'Criteria' };
export const PURPOSE_WORD = 'Network capacity view';

export const MEMBER_STATUS_WORD: Readonly<Record<MemberStatus, string>> = { invited: 'Invited', active: 'Active', left: 'Left', removed: 'Removed' };

export const LISTING_STATUS_WORD: Readonly<Record<ListingStatus, string>> = {
  pending: 'Waiting',
  admitted: 'Admitted',
  suspended: 'Paused',
  declined: 'Declined',
  withdrawn: 'Withdrawn',
};

/** The reasons for a decline or a pause, in the order the screen offers them. A reason is a code, never free text. */
export const REASON_WORDS: readonly [ListingReason, string][] = [
  ['outside-area', 'Outside the area'],
  ['outside-pilot', 'Outside the pilot'],
  ['duplicate-listing', 'Duplicate listing'],
  ['data-quality', 'Data quality'],
  ['safety-concern', 'Safety concern'],
  ['agreement-breach', 'Agreement'],
  ['other', 'Other'],
];
export const reasonWord = (reason: ListingReason | null): string => (reason === null ? '-' : (REASON_WORDS.find(([code]) => code === reason)?.[1] ?? reason));

/** The `Approval` of a grant, said from the point of view of the two approvals it needs. */
export function approvalWord(grant: Pick<GrantRow, 'status' | 'effective' | 'effectiveFrom'>): string {
  switch (grant.status) {
    case 'proposed':
      return 'Waiting for the organisation and the network owner';
    case 'owner-approved':
      return 'Waiting for the organisation';
    case 'grantor-approved':
      return 'Waiting for the network owner';
    case 'approved':
      return grant.effective ? 'Approved' : `Approved, starts on ${dateText(grant.effectiveFrom)}`;
    case 'ended':
      return 'Ended';
    case 'lapsed':
      return 'Lapsed';
    case 'declined':
      return 'Declined';
    case 'superseded':
      return 'Replaced by a newer version';
  }
}

/** True while the network owner's own approval is still to be given (the owner may approve or decline). */
export const waitsForOwner = (grant: Pick<GrantRow, 'status'>): boolean => grant.status === 'proposed' || grant.status === 'grantor-approved';
/** True while the organisation's own approval is still to be given (its administrator may approve or decline). */
export const waitsForOrganisation = (grant: Pick<GrantRow, 'status'>): boolean => grant.status === 'proposed' || grant.status === 'owner-approved';
/** True while a grant is in force or about to be (the grantor may end it). */
export const canEnd = (grant: Pick<GrantRow, 'status'>): boolean => grant.status === 'approved';
