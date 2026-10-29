// Sample capacity links for the tests (sample data only, no patient information).
// The shapes are the back end's GET and POST answers as L01 built them (DEC-167 item 4).
// Times are London summer time on Friday 23 October: 08:15 BST is 07:15 UTC.

export const TENANT_HOST = 'tenant-a.example.test';
export const BACKEND_ROOT = 'http://backend.test';

/** Open links, one per scenario. The token is the bearer; the CSRF token is the back end's HMAC, here `csrf-<token>`. */
export const LINK = {
  /** A figure is on record: 3, as of 08:15, usual range 0 to 8. */
  recorded: 'RecordedLinkTokenAbcdef',
  /** No figure yet. The reply-by time is 08:30 and the next update is due 10:00. */
  empty: 'EmptyLinkTokenAbcdefghi',
  /** Past its reply-by time, or answered: the back end answers 410 for both. */
  expired: 'ExpiredLinkTokenAbcdefgh',
  used: 'UsedLinkTokenAbcdefghijk',
  /** A booking link (L02): the page redirects to /l/[token]/booking. */
  booking: 'BookingLinkTokenAbcdefgh',
  /** The back end cannot be reached. */
  down: 'DownLinkTokenAbcdefghijkl',
  /** The tenant's link budget is used up (429). */
  limited: 'LimitedLinkTokenAbcdefghi',
  /** A confirm that the back end refuses: a figure is needed (409 send-number). */
  stale: 'StaleLinkTokenAbcdefghijkl',
} as const;

export const csrfFor = (token: string) => `csrf-${token}`;

export const RECORDED_VIEW = {
  state: 'ok',
  purpose: 'capacity-reply',
  serviceName: 'UCR West',
  unitLabel: 'referrals in the next 2 hrs',
  recordedValue: 3,
  asOf: '2026-10-23T07:15:00Z',
  usualMin: 0,
  usualMax: 8,
  replyBy: '2026-10-23T09:30:00Z',
  nextDue: '2026-10-23T11:00:00Z',
} as const;

export const EMPTY_VIEW = {
  ...RECORDED_VIEW,
  recordedValue: null,
  asOf: null,
  replyBy: '2026-10-23T07:30:00Z',
  nextDue: '2026-10-23T09:00:00Z',
} as const;

/** What the back end answers after a recorded answer (10:12 BST). */
export const RECORDED_ANSWER = {
  serviceName: 'UCR West',
  value: 3,
  unitLabel: 'referrals in the next 2 hrs',
  recordedAt: '2026-10-23T09:12:00Z',
  nextDue: '2026-10-23T11:00:00Z',
} as const;

export const EXPIRED_BODY = { state: 'expired' } as const;
