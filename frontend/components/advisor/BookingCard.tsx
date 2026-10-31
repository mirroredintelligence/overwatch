'use client';

import { useEffect, useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { ShapeIcon, type Shape } from '@/components/ui/StatusBadge';
import {
  type BookingState,
  type BookingStatus,
  type CancelReason,
  clock,
  declineReasonWording,
  deliveryWording,
  minutesBetween,
} from '@/lib/advisor/bookings';
import { CancelBookingDialog } from './CancelBookingDialog';
import styles from './Advisor.module.css';
import { WithdrawalAlert } from './WithdrawalAlert';

// The booking card an advisor sees for one service after asking it to take the patient (W20, W21). It
// shows what the back end holds now. It changes nothing itself: a cancel goes to the parent, which posts
// it; a withdrawal or not-reached report opens its alert, which is acknowledged only by an explicit
// answer that the caller was phoned or is being helped (DEC-854). Until then the card keeps a notice.

const BADGE: Record<BookingStatus, { word: string; shape: Shape }> = {
  requested: { word: 'Requested', shape: 'dashed-circle' },
  confirmed: { word: 'Booked', shape: 'circle-tick' },
  declined: { word: 'Declined', shape: 'diamond' },
  expired: { word: 'No reply', shape: 'triangle' },
  'cancelled-before': { word: 'Cancelled', shape: 'moon' },
  'cancelled-after': { word: 'Cancelled', shape: 'moon' },
  withdrawn: { word: 'Withdrawn', shape: 'triangle' },
  'not-reached': { word: 'Not reached', shape: 'triangle' },
  completed: { word: 'Completed', shape: 'circle-tick' },
};

const ANNOUNCE: Partial<Record<BookingStatus, string>> = {
  confirmed: 'confirmed booking',
  declined: 'declined booking',
  expired: 'did not reply to booking',
  withdrawn: 'withdrew booking',
  'not-reached': 'could not reach the patient for booking',
  'cancelled-before': 'cancelled booking',
  'cancelled-after': 'cancelled booking',
};

const CONFLICT = 'This booking changed before you cancelled. Check its status.';
// The directory the number is looked up in is the advisor's own: the back end sends no service phone (H-530).
const NO_NUMBER = "This service's phone number is not on this screen. Find it in your service directory.";

export type BookingCardProps = {
  booking: BookingState;
  serviceName: string;
  servicePhone: string | null;
  /** The clock in epoch ms. Defaults to the browser's. */
  now?: () => number;
  /** Cancels this request or booking with a reason. The parent posts it. */
  onCancelBooking?: (reason: CancelReason) => void;
  cancelBusy?: boolean;
  cancelConflict?: boolean;
  /** The advisor answered a withdrawal or not-reached alert: acknowledge it at the back end. True when it was taken. */
  onAcknowledge?: () => Promise<boolean>;
  onSeeOptions?: () => void;
  onBackToOptions?: () => void;
  onNextOption?: () => void;
  onAskClinical?: () => void;
  onRecordOutcome?: () => void;
  onCopySummary?: () => void;
};

function phoneLink(servicePhone: string | null, label: string, dataEl: string) {
  if (servicePhone === null) return <p className={styles.text}>{NO_NUMBER}</p>;
  return (
    <Button variant="secondary" href={`tel:${servicePhone}`} dataEl={dataEl}>
      {label}
    </Button>
  );
}

export function BookingCard(props: BookingCardProps) {
  const { booking, serviceName, servicePhone, now = () => Date.now() } = props;
  const [showPhone, setShowPhone] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  // The prompt's timer fired for this booking state (keyed by id and status), so a new state starts afresh.
  const stateKey = `${booking.id}|${booking.status}`;
  const [firedFor, setFiredFor] = useState<string | null>(null);
  const [acknowledgedFor, setAcknowledgedFor] = useState<string | null>(null);
  // The alert was set aside without an answer for this state: it is not acknowledged, and a notice stands.
  const [leftOpenFor, setLeftOpenFor] = useState<string | null>(null);
  const [lastStatus, setLastStatus] = useState<BookingStatus>(booking.status);
  const [announcement, setAnnouncement] = useState('');

  // The phone prompt: an alert at the prompt time while the request is still open. A timer, not a
  // server read, so it shows on time whatever the back end says in between.
  const pending = booking.status === 'requested';
  // A text that did not arrive is not waited on: the prompt to phone is due at once (H-494).
  const notDelivered = pending && booking.delivery === 'failed';
  const promptDue = pending && (notDelivered || firedFor === stateKey || Date.parse(booking.phonePromptAt) <= now());
  useEffect(() => {
    if (!pending) return;
    const wait = Date.parse(booking.phonePromptAt) - now();
    if (wait <= 0) return;
    const timer = setTimeout(() => setFiredFor(stateKey), wait);
    return () => clearTimeout(timer);
    // The clock is read when the state arrives; a new state (or a new id) starts a new wait.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stateKey, pending, booking.phonePromptAt]);

  // A status change is announced once, politely, and not on the first render. Adjusting state while
  // rendering (not in an effect) keeps the announcement to one update per change.
  if (lastStatus !== booking.status) {
    setLastStatus(booking.status);
    const words = ANNOUNCE[booking.status];
    setAnnouncement(words === undefined ? '' : `${serviceName} ${words} ${booking.reference}`);
  }

  const badge = BADGE[booking.status];
  // Answered in this window, or already answered at the back end (a reload brings the card back with its answer, KI-451).
  const needsAnswer =
    (booking.status === 'withdrawn' || booking.status === 'not-reached') && acknowledgedFor !== stateKey && booking.acknowledgedAt === null;
  const alertOpen = needsAnswer && leftOpenFor !== stateKey;
  const hidden = dialogOpen || alertOpen;
  const cancelled = booking.status === 'cancelled-before' || booking.status === 'cancelled-after';
  const cancellable = booking.status === 'requested' || booking.status === 'confirmed';
  const phone = servicePhone;

  return (
    <>
      <section
        className={styles.card}
        aria-label={`Booking for ${serviceName}`}
        aria-hidden={hidden ? true : undefined}
        data-el="ADV-BOOK-CARD"
      >
        <p className={styles.badge} data-status={booking.status}>
          <ShapeIcon shape={badge.shape} />
          <span>{badge.word}</span>
        </p>

        {booking.status === 'requested' ? (
          <>
            <h3 className={styles.heading}>Not booked yet</h3>
            <p className={styles.text}>
              {`${deliveryWording(booking.delivery)} ${clock(booking.requestedAt)}. Waiting for CONFIRMED. Phone prompt at ${clock(booking.phonePromptAt)}. Request expires ${clock(booking.replyBy)}.`}
            </p>
            <p className={styles.text}>Colleagues see 1 pending on the board.</p>
            {promptDue ? (
              <Banner
                tone="warning"
                title={notDelivered ? `The text to ${serviceName} was not delivered. Phone them now.` : `No reply yet. Phone ${serviceName} now.`}
                dataEl="ADV-BOOK-PROMPT"
              />
            ) : null}
            <div className={styles.actions}>
              <Button variant="secondary" dataEl="ADV-BOOK-PHONE-BTN" onClick={() => setShowPhone(true)}>
                Phone them instead
              </Button>
              {showPhone ? phoneLink(phone, phone ?? '', 'ADV-BOOK-PHONE-LINK') : null}
              <Button variant="neutral" dataEl="ADV-BOOK-CANCEL-BTN" onClick={() => setDialogOpen(true)}>
                Cancel request
              </Button>
            </div>
          </>
        ) : null}

        {booking.status === 'confirmed' ? (
          <>
            <h3 className={styles.heading}>{`Confirmed ${clock(booking.confirmedAt ?? booking.requestedAt)}`}</h3>
            <p className={styles.text}>{`Reference ${booking.reference}. Capacity reduced by 1. Next: complete the referral in SystmOne.`}</p>
            <div className={styles.actions}>
              <Button variant="secondary" dataEl="ADV-BOOK-NEXT-BTN" onClick={() => props.onCopySummary?.()}>
                Copy summary for SystmOne
              </Button>
              <Button variant="neutral" dataEl="ADV-BOOK-OUTCOME-BTN" onClick={() => props.onRecordOutcome?.()}>
                Record outcome
              </Button>
            </div>
          </>
        ) : null}

        {booking.status === 'declined' ? (
          <>
            <h3 className={styles.heading}>Not booked</h3>
            <p className={styles.text}>
              {`Declined ${clock(booking.declinedAt ?? booking.requestedAt)}. Reason: ${declineReasonWording(booking.declineReason)}. Pending count released. Choose another option or phone to discuss.`}
            </p>
            <div className={styles.actions}>
              <Button variant="secondary" dataEl="ADV-BOOK-BACK-BTN" onClick={() => props.onBackToOptions?.()}>
                Back to options
              </Button>
              {phoneLink(phone, 'Phone to discuss', 'ADV-BOOK-DISCUSS-BTN')}
            </div>
          </>
        ) : null}

        {booking.status === 'expired' ? (
          <>
            <h3 className={styles.heading}>Not booked. Phone now.</h3>
            <p className={styles.text}>
              {`No reply after ${minutesBetween(booking.requestedAt, booking.phonePromptAt)} min, so you were prompted to phone. The request expired at ${minutesBetween(booking.requestedAt, booking.replyBy)} min and the pending count is released. Do not assume it was accepted.`}
            </p>
            <div className={styles.actions}>
              {phoneLink(phone, `Phone ${serviceName}`, 'ADV-BOOK-PHONE-NOW-BTN')}
              <Button variant="secondary" dataEl="ADV-BOOK-NEXT-OPTION-BTN" onClick={() => props.onNextOption?.()}>
                Try next option
              </Button>
            </div>
          </>
        ) : null}

        {cancelled ? (
          <>
            <h3 className={styles.heading}>Booking cancelled</h3>
            <p className={styles.text}>Choose another option, or leave this booking as it is.</p>
            <div className={styles.actions}>
              <Button variant="secondary" dataEl="ADV-BOOK-CHOOSE-BTN" onClick={() => props.onSeeOptions?.()}>
                Choose another option
              </Button>
            </div>
          </>
        ) : null}

        {booking.status === 'withdrawn' || booking.status === 'not-reached' ? (
          <p className={styles.text}>
            {booking.acknowledgedAt === null ? badge.word : `${badge.word}. Alert answered at ${clock(booking.acknowledgedAt)}.`}
          </p>
        ) : null}

        {needsAnswer && !alertOpen ? (
          <Banner
            tone="warning"
            title={`${serviceName} ${booking.status === 'withdrawn' ? 'withdrew' : 'could not reach the patient'}. This is not answered yet: phone the caller, then answer the alert.`}
            dataEl="ADV-WITHDRAWN-NOTICE"
          >
            <Button variant="primary" dataEl="ADV-WITHDRAWN-REOPEN-BTN" onClick={() => setLeftOpenFor(null)}>
              Open the alert
            </Button>
          </Banner>
        ) : null}

        {cancellable && !pending && booking.status === 'confirmed' ? (
          <div className={styles.actions}>
            <Button variant="neutral" dataEl="ADV-BOOK-CANCEL-BTN" onClick={() => setDialogOpen(true)}>
              Cancel booking
            </Button>
          </div>
        ) : null}

        {props.cancelConflict ? <Banner tone="warning" title={CONFLICT} dataEl="ADV-BOOK-CONFLICT-NOTICE" /> : null}

        <p role="status" aria-live="polite" className={styles.visuallyHidden}>
          {announcement}
        </p>
      </section>

      {dialogOpen ? (
        <CancelBookingDialog
          kind={pending ? 'request' : 'booking'}
          serviceName={serviceName}
          busy={props.cancelBusy}
          onConfirm={(reason) => {
            setDialogOpen(false);
            props.onCancelBooking?.(reason);
          }}
          onKeep={() => setDialogOpen(false)}
        />
      ) : null}

      {alertOpen ? (
        <WithdrawalAlert
          booking={booking}
          serviceName={serviceName}
          onAcknowledge={async () => {
            const taken = (await props.onAcknowledge?.()) ?? false;
            if (taken) setAcknowledgedFor(stateKey);
            return taken;
          }}
          onLeaveOpen={() => setLeftOpenFor(stateKey)}
          onSeeOptions={() => props.onSeeOptions?.()}
          onAskClinical={props.onAskClinical}
        />
      ) : null}
    </>
  );
}
