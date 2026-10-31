// The words the operator console prints for what the back end names in codes (TEN-083). Pure text. A code
// this module does not know is printed as it is: never guessed at.

export const TENANT_STATUS_WORD: Record<string, string> = {
  provisioning: 'Being set up',
  active: 'Active',
  suspended: 'Suspended',
  offboarding: 'Closing',
  offboarded: 'Closed',
  purged: 'Removed',
};

export const ORGANISATION_TYPE_WORDS: readonly [string, string][] = [
  ['nhs-trust', 'NHS trust'],
  ['icb', 'Integrated care board'],
  ['gp-practice', 'GP practice'],
  ['local-authority', 'Local authority'],
  ['voluntary-independent', 'Voluntary or independent'],
  ['other', 'Other'],
];

export function organisationTypeWord(code: string | null): string {
  if (code === null) return '-';
  return ORGANISATION_TYPE_WORDS.find(([value]) => value === code)?.[1] ?? code;
}

const AUDIT: Record<string, string> = {
  'tenant-created': 'Tenant created',
  'tenant-host-set': 'Address set',
  'tenant-number-recorded': 'Text number recorded',
  'tenant-number-tested': 'Text number tested',
  'tenant-references-recorded': 'References recorded',
  'tenant-directory-verified': 'Directory verified',
  'tenant-admin-invited': 'First administrator invited',
  'tenant-activated': 'Tenant activated',
  'tenant-suspended': 'Tenant suspended',
  'tenant-resumed': 'Tenant resumed',
  'tenant-offboarding-started': 'Closing started',
  'operator-signed-in': 'Signed in',
  'support-ticket-requested': 'Support access requested',
  'support-ticket-cancelled': 'Support request cancelled',
  'support-ticket-approved': 'Support request approved',
  'support-ticket-refused': 'Support request refused',
  'support-ticket-revoked': 'Support request taken back',
  'support-ticket-opened': 'Support request opened',
  'support-ticket-ended': 'Support request ended',
  'support-access-opened': 'Support access opened',
  'support-access-used': 'Support access used',
  'support-access-ended': 'Support access ended',
  'support-access-revoked': 'Support access taken back',
  'support-access-refused': 'Support access refused',
  'support-access-aborted': 'Support access stopped',
};

export function auditWord(action: string): string {
  return AUDIT[action] ?? action;
}

/** A ticket's state from the support person's side. */
export const SUPPORT_STATE_WORD: Record<string, string> = {
  pending: 'Waiting for the tenant’s administrator',
  approved: 'Approved. Ask the administrator for the code.',
  refused: 'Refused',
  cancelled: 'Cancelled',
  opened: 'Open now',
  ended: 'Ended',
  revoked: 'Taken back by the administrator',
  expired: 'Lapsed',
};

export function supportStateWord(state: string): string {
  return SUPPORT_STATE_WORD[state] ?? state;
}

export const TENANT_ID_PATTERN = /^[a-z0-9][a-z0-9-]{1,30}$/;
export const TICKET_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;
