'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { sendAnswer } from '@/lib/links/browser';
import { londonHm, type LinkAnswer, type LinkView, splitUnitLabel } from '@/lib/links/model';
import styles from './CapacityLink.module.css';
import { LinkExpired } from './LinkExpired';
import { FigureCard } from './parts/FigureCard';
import { LinkFrame } from './parts/LinkFrame';
import { NumberStepper } from './parts/NumberStepper';
import { StateBanner, type StateBannerTone } from './parts/StateBanner';

// The reporter's answer to a capacity link (artboards B1, B2, B3, D1): confirm the figure on record, send a
// new one, or say the service is closed. Opening the page changes nothing; only a press posts. The figure
// card never moves: only the controls around it open and close. A figure far outside the usual range, and
// "closed to referrals", are each asked about once before they are sent. When a send does not get through
// the page says so, keeps the number (in memory only: the address holds a bearer token, so nothing is
// stored) and offers to send the same answer again, with the same CSRF token.

type Mode = 'main' | 'change' | 'range' | 'closed' | 'unsent';

type Notice = { tone: StateBannerTone; lead: string; detail?: string };

const MESSAGES = {
  'send-number': 'Please send the number.',
  'rate-limited': 'Too many tries. Wait a few minutes, then try again.',
} as const;

const WIDE = '(min-width: 900px)';

function subscribeWide(onChange: () => void): () => void {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return () => undefined;
  const query = window.matchMedia(WIDE);
  query.addEventListener('change', onChange);
  return () => query.removeEventListener('change', onChange);
}

const isWide = (): boolean => typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(WIDE).matches;

type Props = { token: string; view: LinkView };

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function CapacityResponder({ token, view }: Props) {
  const router = useRouter();
  const { noun, window: windowText } = splitUnitLabel(view.unitLabel);
  const wide = useSyncExternalStore(subscribeWide, isWide, () => false);
  const [mode, setMode] = useState<Mode>('main');
  const [value, setValue] = useState<number | null>(view.recordedValue);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  // A figure the back end said is outside the usual range, waiting to be confirmed.
  const [range, setRange] = useState<{ value: number; min: number; max: number } | null>(null);
  // The answer that did not get through, kept so it can be sent again. `offline` says whether the phone knew it had no signal.
  const [unsent, setUnsent] = useState<{ answer: LinkAnswer; offline: boolean } | null>(null);
  const [backOnline, setBackOnline] = useState(false);
  // Set when the link has closed since the page loaded: the renewal token its answer carried, or null.
  const [expired, setExpired] = useState<{ csrfToken: string | null } | null>(null);
  const page = useRef<HTMLElement>(null);
  const firstRender = useRef(true);

  // Focus moves to the new heading after each step (not on the first paint).
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    const heading = page.current?.querySelector('h1');
    if (heading instanceof HTMLElement) {
      heading.setAttribute('tabindex', '-1');
      heading.focus();
    }
  }, [mode]);

  // "Back online." is said once, when the signal returns while an answer is waiting to be sent.
  const waiting = unsent !== null && unsent.offline;
  useEffect(() => {
    if (!waiting) return;
    const onOnline = () => setBackOnline(true);
    window.addEventListener('online', onOnline);
    return () => window.removeEventListener('online', onOnline);
  }, [waiting]);

  if (expired !== null) return <LinkExpired token={token} csrfToken={expired.csrfToken} />;

  const recorded = view.recordedValue !== null;
  const asOf = view.asOf === null ? undefined : londonHm(view.asOf);
  const until = londonHm(view.replyBy);
  const nextDue = view.nextDue === null ? null : londonHm(view.nextDue);
  const nextDueText = nextDue === null ? '' : ` Next update due ${nextDue}.`;

  async function send(answer: LinkAnswer) {
    setBusy(true);
    setNotice(null);
    setBackOnline(false);
    const outcome = await sendAnswer(token, view.csrfToken, answer);
    switch (outcome.kind) {
      case 'recorded':
        // Keep busy while the thank-you page opens, so nothing posts twice.
        // The address holds no link token (the link is spent) and only the sealed detail (KI-179).
        router.push(outcome.thanks === null ? '/l/thanks' : `/l/thanks?d=${encodeURIComponent(outcome.thanks)}`);
        return;
      case 'out-of-range':
        setBusy(false);
        setUnsent(null);
        setRange({ value: answer.action === 'number' ? answer.value : (value ?? 0), min: outcome.usualMin, max: outcome.usualMax });
        setMode('range');
        return;
      case 'gone':
        setBusy(false);
        setExpired({ csrfToken: outcome.csrfToken });
        return;
      case 'send-number':
        setBusy(false);
        setUnsent(null);
        setNotice({ tone: 'warning', lead: MESSAGES['send-number'] });
        setMode('change');
        return;
      case 'rate-limited':
        setBusy(false);
        setNotice({ tone: 'warning', lead: MESSAGES['rate-limited'] });
        return;
      default:
        setBusy(false);
        setUnsent({ answer, offline: typeof navigator !== 'undefined' && navigator.onLine === false });
        setMode('unsent');
    }
  }

  const open = wide || mode === 'change' || !recorded;
  const sendFigure = () => {
    if (value !== null) void send({ action: 'number', value });
  };

  const banner: Notice | null =
    notice ??
    (mode === 'unsent' && unsent !== null
      ? unsent.offline && !backOnline
        ? { tone: 'offline', lead: 'No signal. Not sent yet.', detail: 'Nothing has been lost. Your number is still here.' }
        : unsent.offline
          ? { tone: 'info', lead: 'Back online.', detail: 'Your number is still here.' }
          : { tone: 'error', lead: 'We could not send that.', detail: 'Your number is still here. Try again, or phone the shift lead.' }
      : null);

  let body: React.ReactNode;
  if (mode === 'closed') {
    body = (
      <>
        <section className={`${styles.card} ${styles.cardStart}`}>
          <span className={`${styles.tag} ${styles.tagDark}`}>
            <svg width="16" height="16" viewBox="0 0 20 20" aria-hidden="true" focusable="false">
              <rect x="3" y="3" width="14" height="14" rx="2" fill="none" stroke="currentColor" strokeWidth="2" />
              <path d="M7 7l6 6M13 7l-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
            Closed to referrals
          </span>
          <h1 className={styles.heading}>{`Tell advisors ${view.serviceName} is closed?`}</h1>
          <p className={styles.body}>{`Advisors will not be offered ${view.serviceName}. It shows as closed on the board until you send a number.`}</p>
        </section>
        <button type="button" className={`${styles.btn} ${styles.primary} ${styles.primaryDark}`} disabled={busy} aria-busy={busy ? 'true' : undefined} data-el="REP-LINK-CLOSED-CONFIRM-BTN" onClick={() => void send({ action: 'closed' })}>
          Yes, we are closed
        </button>
        <button type="button" className={`${styles.btn} ${styles.outline}`} disabled={busy} onClick={() => setMode('main')}>
          No, go back
        </button>
        <p className={styles.note}>You can send a number later from the next prompt, or phone the shift lead.</p>
      </>
    );
  } else if (mode === 'range' && range !== null) {
    body = (
      <>
        <FigureCard service={view.serviceName} figure={range.value} unit={view.unitLabel} />
        <div className={styles.ask}>
          <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
            <path d="M12 3l10 18H2z" />
            <path d="M12 10v5M12 18.2h.01" />
          </svg>
          <div>
            <p className={styles.askTitle}>{`Is ${range.value} right?`}</p>
            <p className={styles.askText}>
              {`That is far ${range.value > range.max ? 'above' : 'below'} your usual range of ${range.min} to ${range.max}. If it is right, send it. The shift lead will be told so they can check.`}
            </p>
          </div>
        </div>
        <button type="button" className={`${styles.btn} ${styles.primary}`} disabled={busy} aria-busy={busy ? 'true' : undefined} data-el="REP-LINK-RANGE-CONFIRM-BTN" onClick={() => void send({ action: 'number', value: range.value, confirmOutOfRange: true })}>
          {`Yes, send ${range.value}`}
        </button>
        <button type="button" className={`${styles.btn} ${styles.outline}`} disabled={busy} onClick={() => setMode('change')}>
          Change the number
        </button>
        <p className={styles.note}>Nothing is recorded until you press a button.</p>
      </>
    );
  } else if (mode === 'unsent' && unsent !== null) {
    const pending = unsent.answer.action === 'number' ? unsent.answer.value : unsent.answer.action === 'confirm' ? view.recordedValue : null;
    body = (
      <>
        <FigureCard service={view.serviceName} figure={pending} unit={view.unitLabel}>
          <p>Closed to referrals.</p>
        </FigureCard>
        <span className={`${styles.tag} ${styles.tagDashed}`}>Not sent yet</span>
        <button type="button" className={`${styles.btn} ${styles.primary}`} disabled={busy} aria-busy={busy ? 'true' : undefined} data-el="REP-LINK-RETRY-BTN" onClick={() => void send(unsent.answer)}>
          Try again now
        </button>
        <p className={styles.note}>{`The link stays open until ${until}. Keep this page open, or reply to the text with the number.`}</p>
      </>
    );
  } else {
    const showConfirm = recorded && (mode === 'main' || wide);
    const showDifferent = recorded && !wide && mode === 'main';
    const showBack = recorded && !wide && mode === 'change';
    const showClosed = !(recorded && !wide && mode === 'change');
    const title = !recorded ? undefined : wide ? 'Or send a different number' : `New number of ${noun}`;
    const sendClass = !showConfirm ? `${styles.primary} ${value === null ? styles.off : ''}` : styles.outline;
    body = (
      <>
        <FigureCard
          service={view.serviceName}
          label={recorded ? 'Capacity update' : 'First update'}
          replyBy={until}
          figure={view.recordedValue}
          unit={view.unitLabel}
          recordedAt={asOf}
          recordedNote={showConfirm ? 'Still right?' : undefined}
          dataEl="REP-LINK-FIGURE"
        >
          <p>{`How many ${noun} can you take${windowText ? ` ${windowText}` : ''}?`}</p>
        </FigureCard>

        {showConfirm ? (
          <button type="button" className={`${styles.btn} ${styles.primary}`} disabled={busy} aria-busy={busy ? 'true' : undefined} data-el="REP-LINK-CONFIRM-BTN" onClick={() => void send({ action: 'confirm' })}>
            {`Yes, still ${view.recordedValue}`}
          </button>
        ) : null}
        {showDifferent ? (
          <button type="button" className={`${styles.btn} ${styles.outline}`} disabled={busy} aria-expanded="false" data-el="REP-LINK-DIFFERENT-BTN" onClick={() => setMode('change')}>
            Send a different number
          </button>
        ) : null}

        {open ? (
          <>
            <div className={`${styles.card} ${styles.cardCentre}`}>
              <NumberStepper
                label={capitalise(view.unitLabel)}
                title={title}
                value={value}
                unit={noun}
                usualMin={view.usualMin}
                usualMax={view.usualMax}
                onChange={setValue}
                dataEl="REP-LINK-STEPPER"
              />
            </div>
            <button
              type="button"
              className={`${styles.btn} ${sendClass}`}
              disabled={busy || value === null}
              aria-busy={busy ? 'true' : undefined}
              data-el="REP-LINK-SEND-BTN"
              onClick={sendFigure}
            >
              {value === null ? 'Choose a number to send' : `Send ${value}`}
            </button>
          </>
        ) : null}

        {showBack ? (
          <button type="button" className={`${styles.btn} ${styles.dashed} ${styles.plain}`} disabled={busy} onClick={() => setMode('main')}>
            Back
          </button>
        ) : null}
        {showClosed ? (
          <button type="button" className={`${styles.btn} ${styles.dashed}`} disabled={busy} data-el="REP-LINK-CLOSED-BTN" onClick={() => setMode('closed')}>
            We are closed to referrals
          </button>
        ) : null}

        <p className={styles.note}>
          {recorded ? `This link works once and is for this phone. It closes at ${until}.` : `This link works once and closes at ${until}.`}
          {nextDueText}
        </p>
      </>
    );
  }

  return (
    <LinkFrame>
      <main ref={page} className={styles.stack}>
        {banner !== null ? (
          <StateBanner tone={banner.tone} lead={banner.lead} dataEl="REP-LINK-NOTICE">
            {banner.detail}
          </StateBanner>
        ) : null}
        {body}
        <p role="status" className={styles.srOnly}>
          {busy ? 'Sending your answer.' : ''}
        </p>
      </main>
    </LinkFrame>
  );
}
