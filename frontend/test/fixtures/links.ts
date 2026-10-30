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
  /** A booking request link (L02, `booking-request`): open, not yet answered. */
  booking: 'BookingLinkTokenAbcdefgh',
  /** A booking request that the service has already declined: GET answers 410 `declined`. */
  bookingDeclined: 'DeclinedBookingTokenAbcdef',
  /** A booking request whose answer is refused as taken (409 `declined`) once it is open. */
  bookingTaken: 'TakenBookingTokenAbcdefghi',
  /** A confirmed booking's change link (L02, `booking-change`): open. */
  bookingChange: 'BookingChangeTokenAbcdefg',
  /** A change link whose booking was cancelled by the SPOA: GET answers 410 `cancelled`. */
  bookingCancelled: 'CancelledBookingTokenAbcd',
  /** A change link whose withdrawal is refused as taken (409 `withdrawn`). */
  bookingChangeTaken: 'TakenChangeTokenAbcdefghi',
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

export type LinkReplyFor = { status: number; body: Record<string, unknown>; headers?: Record<string, string> };

const CSRF_OK = (token: string, given: string | null) => given === csrfFor(token);

/** The booking request view as L02 answers it (booking_links.py view_body): no postcode, name or case. */
export const BOOKING_REQUEST_VIEW = {
  state: 'ok',
  purpose: 'booking-request',
  reference: '4821',
  serviceName: 'UCR West',
  ageBand: '80+',
  need: 'fall-no-injury and frailty',
  urgency: 'within 2 hrs',
  replyBy: '2026-10-23T13:26:00Z',
  bookingStatus: 'requested',
  coordinationPhone: '0300 123 4567',
} as const;

/** The change view of a confirmed booking as L02 answers it (booking-change). */
export const BOOKING_CHANGE_VIEW = {
  state: 'ok',
  purpose: 'booking-change',
  reference: '4821',
  serviceName: 'UCR West',
  ageBand: '80+',
  need: 'fall-no-injury and frailty',
  urgency: 'within 2 hrs',
  bookingStatus: 'confirmed',
  coordinationPhone: '0300 123 4567',
} as const;

/** The change token a confirmed booking is given (L02, 24 hours). */
export const BOOKING_CHANGE_TOKEN = 'ChangeTokenAbcdefghijklmnop';

const VIEW_FOR_OPEN: Partial<Record<string, Record<string, unknown>>> = {
  [LINK.recorded]: RECORDED_VIEW as unknown as Record<string, unknown>,
  [LINK.empty]: EMPTY_VIEW as unknown as Record<string, unknown>,
  [LINK.booking]: BOOKING_REQUEST_VIEW as unknown as Record<string, unknown>,
  [LINK.bookingTaken]: BOOKING_REQUEST_VIEW as unknown as Record<string, unknown>,
  [LINK.bookingChange]: BOOKING_CHANGE_VIEW as unknown as Record<string, unknown>,
  [LINK.bookingChangeTaken]: BOOKING_CHANGE_VIEW as unknown as Record<string, unknown>,
  [LINK.limited]: RECORDED_VIEW as unknown as Record<string, unknown>,
  [LINK.stale]: RECORDED_VIEW as unknown as Record<string, unknown>,
};

/** What the back end answers to `GET /links/{token}` (the view, with its CSRF token). */
/** The state a closed link answers with on GET (L01/L02: a 410 carries the state word and nothing else). */
const GONE_ON_GET: Partial<Record<string, string>> = {
  [LINK.used]: 'used',
  [LINK.bookingDeclined]: 'declined',
  [LINK.bookingCancelled]: 'cancelled',
};

export function linkViewReply(token: string): LinkReplyFor {
  if (token === LINK.down) return { status: 503, body: { state: 'error' } };
  const view = VIEW_FOR_OPEN[token];
  if (view === undefined) return { status: 410, body: { state: GONE_ON_GET[token] ?? 'expired' } };
  return { status: 200, body: { ...view, csrfToken: csrfFor(token) } };
}

/** What the back end answers to `POST /links/{token}` with an answer and the CSRF token the caller sent. */
export function linkAnswerReply(token: string, given: string | null, body: Record<string, unknown>): LinkReplyFor {
  if (!CSRF_OK(token, given)) return { status: 403, body: { state: 'forbidden' } };
  const booking = bookingAnswerReply(token, body);
  if (booking !== undefined) return booking;
  if (token === LINK.expired) return { status: 410, body: { state: 'expired' } };
  if (token === LINK.used) return { status: 410, body: { state: 'used' } };
  if (token === LINK.limited) return { status: 429, body: { state: 'rate-limited' }, headers: { 'Retry-After': '600' } };
  if (token === LINK.stale) return { status: 409, body: { state: 'send-number', reason: 'stale', message: 'Please send the number' } };
  if (body.action === 'confirm') return { status: 200, body: { ...RECORDED_ANSWER } };
  if (body.action === 'closed') return { status: 200, body: { ...RECORDED_ANSWER, value: 0 } };
  if (body.action === 'number') {
    const value = body.value as number;
    if (value > RECORDED_VIEW.usualMax && body.confirmOutOfRange !== true) {
      return { status: 422, body: { state: 'out-of-range', usualMin: RECORDED_VIEW.usualMin, usualMax: RECORDED_VIEW.usualMax } };
    }
    return { status: 200, body: { ...RECORDED_ANSWER, value } };
  }
  return { status: 400, body: { state: 'invalid' } };
}

/** The booking answers (L02): a confirm or decline, a withdrawal or a not-reached report. */
function bookingAnswerReply(token: string, body: Record<string, unknown>): LinkReplyFor | undefined {
  if (token === LINK.bookingTaken) return { status: 409, body: { state: 'declined' } };
  if (token === LINK.bookingChangeTaken) return { status: 409, body: { state: 'withdrawn' } };
  if (token === LINK.bookingDeclined || token === LINK.bookingCancelled) return { status: 410, body: { state: GONE_ON_GET[token] } };
  if (body.action === 'confirm' && token === LINK.booking) {
    return { status: 200, body: { bookingStatus: 'confirmed', changeToken: BOOKING_CHANGE_TOKEN } };
  }
  if (body.action === 'decline' && token === LINK.booking) return { status: 200, body: { bookingStatus: 'declined' } };
  if (body.action === 'withdraw' && token === LINK.bookingChange) return { status: 200, body: { bookingStatus: 'withdrawn' } };
  if (body.action === 'not-reached' && token === LINK.bookingChange) return { status: 200, body: { bookingStatus: 'not-reached' } };
  return undefined;
}

/** What the back end answers to `POST /links/{token}/renew`. */
export function linkRenewReply(token: string): LinkReplyFor {
  if (token === LINK.limited) return { status: 429, body: { state: 'rate-limited' }, headers: { 'Retry-After': '600' } };
  return { status: 202, body: { state: 'accepted' } };
}
