'use client';

import { useEffect, useRef, useState } from 'react';
import { Loading, Skeleton } from '@/components/ui/Skeleton';
import { ReasonChips } from '../parts/ReasonChips';
import { ReplyByTag } from '../parts/ReplyByTag';
import { StateBanner, type StateBannerTone } from '../parts/StateBanner';
import { StatusMark } from '../parts/StatusMark';
import styles from './BookingDecisionView.module.css';

// One booking request, for the link (/l/[token]/booking) and the app (/app/booking/[ref]) alike (artboard B4,
// shared states St). The view knows no data path: the page that wraps it reads the booking, posts the answer
// and tells the view which screen to show. The view owns only what a person chooses on the page: whether the
// decline reasons are open, and which reason. Opening the page books nothing; only Confirm, or Decline
// booking after the reasons, posts. Confirm is the one primary; Decline is outlined and the last step is dark,
// never red.

export type BookingNotice = { tone: StateBannerTone; text: string };

export type BookingScreen =
  | { kind: 'loading'; label: string }
  | { kind: 'failed'; lead: string; text?: string }
  | {
      kind: 'request';
      reference: string;
      service: string;
      ageBand: string | null;
      need: string | null;
      urgency: string | null;
      /** The reply-by time, already formatted ("14:26"), or null when the booking has none. */
      replyBy: string | null;
      /** Set when the phone holds several services: the page says which one this request is for. */
      onlyService: boolean;
      confirmLabel: string;
      /** The words under the facts: where the referral details follow. */
      note: string;
    }
  | { kind: 'booked'; reference: string; service: string; confirmedAt: string | null; note: string; changeHref: string | null }
  | { kind: 'declined'; reference: string; declinedAt: string | null }
  | { kind: 'closed'; heading: string; detail: string | null; phoneAsk: boolean };

export type BookingDecisionViewProps = {
  screen: BookingScreen;
  /** The coordination team's number, or null when the tenant has none. */
  phone: string | null;
  /** An answer is in flight: every button waits, so a second press sends nothing. */
  busy?: boolean;
  /** What went wrong with the last answer; the request stays, nothing is lost. */
  notice?: BookingNotice | null;
  /** The prefix of the data-el ids (SVC-BOOK for the link, REP-BOOK for the app). */
  dataElPrefix: string;
  onConfirm: () => void;
  onDecline: (reason: string | null) => void;
};

const REASONS = [
  { value: 'full', label: 'We are full' },
  { value: 'outside-criteria', label: 'Outside our criteria' },
  { value: 'staffing-or-transport', label: 'Staffing or transport' },
  { value: 'other', label: 'Other' },
] as const;

const capitalise = (text: string): string => text.charAt(0).toUpperCase() + text.slice(1);

function Phone({ phone, lead, none }: { phone: string | null; lead: string; none: string }) {
  if (phone === null) return <>{none}</>;
  return (
    <>
      {lead} <a className={styles.phone} href={`tel:${phone.replace(/\s+/g, '')}`}>{phone}</a>.
    </>
  );
}

export function BookingDecisionView({ screen, phone, busy = false, notice = null, dataElPrefix, onConfirm, onDecline }: BookingDecisionViewProps) {
  const [deciding, setDeciding] = useState(false);
  const [reason, setReason] = useState<string | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const refocus = useRef(false);

  // Opening or closing the reasons moves the focus to the new heading, so a keyboard or screen reader
  // person lands on the new question. It does not run on the first render.
  useEffect(() => {
    if (!refocus.current) return;
    refocus.current = false;
    heading.current?.focus();
  }, [deciding]);

  const toggle = (open: boolean) => {
    refocus.current = true;
    setDeciding(open);
  };

  switch (screen.kind) {
    case 'loading':
      return (
        <main className={styles.stack}>
          <Loading label={screen.label}>
            <div className={styles.card}>
              <Skeleton shape="line" width="50%" />
              <Skeleton shape="title" width="70%" />
              <Skeleton shape="block" />
              <Skeleton shape="line" width="60%" />
            </div>
            <Skeleton shape="chip" width="100%" />
            <Skeleton shape="chip" width="100%" />
          </Loading>
        </main>
      );

    case 'failed':
      return (
        <main className={styles.stack}>
          <StateBanner tone="error" lead={screen.lead}>
            {screen.text}
          </StateBanner>
        </main>
      );

    case 'closed':
      return (
        <main className={styles.stack}>
          <section className={styles.card}>
            <StatusMark tone="closed" dataEl={`${dataElPrefix}-CLOSED-MARK`} />
            <h1 className={styles.heading}>{screen.heading}</h1>
            {screen.detail !== null ? <p className={styles.body}>{screen.detail}</p> : null}
            {screen.phoneAsk ? (
              <p className={styles.body}>
                <Phone
                  phone={phone}
                  lead="If you can still take this patient, phone the coordination team on"
                  none="If you can still take this patient, phone the coordination team."
                />
              </p>
            ) : null}
          </section>
        </main>
      );

    case 'booked':
      return (
        <main className={styles.stack}>
          <section className={styles.card}>
            <StatusMark tone="done" dataEl={`${dataElPrefix}-BOOKED-MARK`} />
            <h1 className={styles.heading}>Booked</h1>
            <p className={styles.body}>
              {`Reference ${screen.reference}, ${screen.service}.${screen.confirmedAt === null ? '' : ` Confirmed ${screen.confirmedAt}.`} The advisor has been told.`}
            </p>
            <p className={styles.bodySmall}>{screen.note}</p>
          </section>
          <section className={styles.card}>
            <h2 className={styles.subhead}>Something changed?</h2>
            <p className={styles.body}>
              {screen.changeHref === null ? (
                <Phone phone={phone} lead="Phone the coordination team on" none="Phone the coordination team." />
              ) : (
                <>
                  Tell us here so the shift lead can act at once.{' '}
                  <Phone phone={phone} lead="Or phone the coordination team on" none="Or phone the coordination team." />
                </>
              )}
            </p>
            {screen.changeHref !== null ? (
              <a className={`${styles.btn} ${styles.outline}`} href={screen.changeHref} data-el={`${dataElPrefix}-CHANGE-LINK`}>
                Tell us something changed
              </a>
            ) : null}
          </section>
          <p className={styles.noteLarge}>You can close this page.</p>
        </main>
      );

    case 'declined':
      return (
        <main className={styles.stack}>
          <section className={styles.card}>
            <StatusMark tone="closed" dataEl={`${dataElPrefix}-DECLINED-MARK`} />
            <h1 className={styles.heading}>Declined</h1>
            <p className={styles.body}>{`Reference ${screen.reference} declined. The advisor has been told.`}</p>
            {screen.declinedAt !== null ? <p className={styles.bodySmall}>{`Declined ${screen.declinedAt}.`}</p> : null}
          </section>
          <p className={styles.noteLarge}>You can close this page.</p>
        </main>
      );

    case 'request': {
      const facts = [
        { label: 'Age band', value: screen.ageBand },
        { label: 'Need', value: screen.need },
        { label: 'Wanted', value: screen.urgency },
      ].filter((fact): fact is { label: string; value: string } => fact.value !== null);
      const noticeBanner =
        notice === null ? null : <StateBanner tone={notice.tone} lead={notice.text} dataEl={`${dataElPrefix}-NOTICE`} />;

      if (deciding) {
        const summary = [screen.ageBand, screen.need, screen.urgency].filter((part): part is string => part !== null).map(capitalise).join(' · ');
        return (
          <main className={styles.stack}>
            <section className={styles.card} aria-label="The request">
              <p className={styles.label}>{`Booking request ${screen.reference} · ${screen.service}`}</p>
              {summary !== '' ? <p className={styles.summary}>{summary}</p> : null}
            </section>
            <section className={styles.card}>
              <h1 className={styles.question} ref={heading} tabIndex={-1}>
                Why can you not take this patient?
              </h1>
              <p className={styles.hint}>Optional. It helps the advisor choose again.</p>
              <ReasonChips
                label="Reason for declining"
                options={REASONS}
                value={reason}
                onChange={setReason}
                disabled={busy}
                dataEl={`${dataElPrefix}-REASONS`}
              />
            </section>
            <button
              type="button"
              className={`${styles.btn} ${styles.dark}`}
              disabled={busy}
              aria-busy={busy ? 'true' : undefined}
              data-el={`${dataElPrefix}-DECLINE-SEND-BTN`}
              onClick={() => onDecline(reason)}
            >
              Decline booking
            </button>
            <button
              type="button"
              className={`${styles.btn} ${styles.outline}`}
              disabled={busy}
              data-el={`${dataElPrefix}-DECLINE-BACK-BTN`}
              onClick={() => toggle(false)}
            >
              Back to the request
            </button>
            {noticeBanner}
            <p className={styles.note}>The advisor is told at once and will choose another service.</p>
          </main>
        );
      }

      return (
        <main className={styles.stack}>
          <section className={styles.card}>
            <div className={styles.cardTop}>
              <span className={styles.label}>{`Booking request ${screen.reference}`}</span>
              {screen.replyBy !== null ? <ReplyByTag time={screen.replyBy} /> : null}
            </div>
            <h1 className={styles.heading} ref={heading} tabIndex={-1}>
              {screen.service}
            </h1>
            {screen.onlyService ? <span className={styles.only}>{`${screen.service} only`}</span> : null}
            {facts.length > 0 ? (
              <dl className={styles.facts}>
                {facts.map((fact) => (
                  <div key={fact.label} className={styles.fact}>
                    <dt>{fact.label}</dt>
                    <dd>{capitalise(fact.value)}</dd>
                  </div>
                ))}
              </dl>
            ) : null}
            <p className={styles.cardNote}>{screen.note}</p>
          </section>
          <button
            type="button"
            className={`${styles.btn} ${styles.primary}`}
            disabled={busy}
            aria-busy={busy ? 'true' : undefined}
            data-el={`${dataElPrefix}-CONFIRM-BTN`}
            onClick={onConfirm}
          >
            {screen.confirmLabel}
          </button>
          <button
            type="button"
            className={`${styles.btn} ${styles.outlineDark}`}
            disabled={busy}
            data-el={`${dataElPrefix}-DECLINE-BTN`}
            onClick={() => toggle(true)}
          >
            Decline
          </button>
          {noticeBanner}
          <p className={styles.note}>Opening this page booked nothing. It is booked when you press Confirm.</p>
        </main>
      );
    }
  }
}
