'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import { FigureCard } from '@/components/reporter/parts/FigureCard';
import { NumberStepper } from '@/components/reporter/parts/NumberStepper';
import { StateBanner, type StateBannerTone } from '@/components/reporter/parts/StateBanner';
import { Loading, Skeleton } from '@/components/ui/Skeleton';
import { splitUnitLabel } from '@/lib/links/model';
import { bffRequest } from '@/lib/reporter/browser';
import { clock } from '@/lib/reporter/times';
import styles from '@/components/reporter/CapacityLink.module.css';

// One service's capacity prompt in the app (artboards B6 and B2, the same steps as the link page, inside the
// app frame). Opening the page changes nothing; only a press posts. The figure card stays put and only the
// controls around it open and close. A figure out of the usual range is asked about once and kept, and a
// second send with the same figure confirms it; "closed to referrals" is asked about once too. Two confirms
// a day are the most the back end takes; after that only a number can be sent. An answer that did not get
// through is kept (in memory only) and sent again with the SAME Idempotency-Key, so the back end records it once.

type Mode = 'main' | 'change' | 'range' | 'closed' | 'unsent';

export type Answer = { kind: 'confirm' } | { kind: 'number'; value: number } | { kind: 'closed' };

type Prompt = {
  service: string;
  unitLabel: string;
  recordedValue: number | null;
  asOf: string | null;
  low: number;
  high: number;
  replyBy: string | null;
  nextDue: string | null;
};

type Notice = { tone: StateBannerTone; lead: string; detail?: string };

const CONFIRM_LIMIT_TEXT = 'You confirmed twice already. Please send the number.';
const SEND_NUMBER_TEXT = 'We cannot confirm that figure now. Please send the number.';

type Reported = { result?: string; serviceName?: string; value?: number; recordedAt?: string; nextDue?: string | null; low?: number; high?: number };

/** The back end's prompt, its instants shown as the tenant's clock time. */
function readPrompt(body: unknown): Prompt | null {
  const v = body as Partial<Record<keyof Prompt, unknown>> | undefined;
  if (typeof v?.service !== 'string' || typeof v.unitLabel !== 'string' || typeof v.low !== 'number' || typeof v.high !== 'number') return null;
  const recorded = typeof v.recordedValue === 'number' ? v.recordedValue : null;
  const time = (value: unknown) => (typeof value === 'string' ? clock(value) || null : null);
  return { service: v.service, unitLabel: v.unitLabel, recordedValue: recorded, asOf: time(v.asOf), low: v.low, high: v.high, replyBy: time(v.replyBy), nextDue: time(v.nextDue) };
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function RespondScreen({ serviceId }: { serviceId: string }) {
  const router = useRouter();
  const [prompt, setPrompt] = useState<Prompt | null>(null);
  const [failed, setFailed] = useState(false);
  const [mode, setMode] = useState<Mode>('main');
  // What the stepper shows once it is touched; until then it starts at the figure on record (undefined = untouched).
  const [edited, setValue] = useState<number | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [confirmAllowed, setConfirmAllowed] = useState(true);
  // A figure the back end said is outside the usual range, waiting to be confirmed, and the range it named.
  const [flagged, setFlagged] = useState<{ value: number; low: number; high: number } | null>(null);
  // The answer that did not get through, with the key it was sent under. `offline` says whether the phone knew it had no signal.
  const [unsent, setUnsent] = useState<{ answer: Answer; key: string; offline: boolean } | null>(null);
  const page = useRef<HTMLElement>(null);
  const firstRender = useRef(true);

  useEffect(() => {
    let live = true;
    void bffRequest(`/api/bff/reporter/services/${encodeURIComponent(serviceId)}/prompt`).then((reply) => {
      if (!live) return;
      if (reply.status === 401) return router.replace('/app/pin');
      const read = reply.status === 200 ? readPrompt(reply.body) : null;
      if (read === null) return setFailed(true);
      setPrompt(read);
    });
    return () => {
      live = false;
    };
  }, [serviceId, router]);

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

  if (failed) {
    return (
      <main className={styles.stack}>
        <StateBanner tone="error" lead="We could not load this service.">
          Try again shortly.
        </StateBanner>
      </main>
    );
  }
  if (prompt === null) {
    return (
      <main className={styles.stack}>
        <Loading label="Opening the update.">
          <Skeleton shape="line" width="50%" />
          <Skeleton shape="title" width="70%" />
          <Skeleton shape="block" />
          <Skeleton shape="block" />
        </Loading>
      </main>
    );
  }

  const { noun, window: windowText } = splitUnitLabel(prompt.unitLabel);
  const recorded = prompt.recordedValue !== null;
  const value = edited === undefined ? prompt.recordedValue : edited;
  const nextDueText = prompt.nextDue === null ? '' : `Next update due ${prompt.nextDue}.`;

  const send = async (answer: Answer, retryKey?: string) => {
    setBusy(true);
    setNotice(null);
    const body: Record<string, unknown> = { ...answer };
    if (answer.kind === 'number' && flagged?.value === answer.value) body.confirmOutOfRange = true;
    // One key for this press, kept for a send again of the same answer: the BFF repeats a write once when its
    // token was stale, with the same key.
    const key = retryKey ?? crypto.randomUUID();
    const reply = await bffRequest(`/api/bff/reporter/services/${encodeURIComponent(serviceId)}/report`, {
      method: 'POST',
      body,
      headers: { 'Idempotency-Key': key },
    });
    const result = reply.body as Reported | undefined;
    if (reply.status === 401) return router.replace('/app/pin');
    if (reply.status === 200 && result?.result === 'recorded' && typeof result.value === 'number' && typeof result.recordedAt === 'string') {
      // The address carries what was just recorded (the service, the figure and the instants), never a
      // number, a token or a patient detail; the thanks page shows the instants as clock time. Busy stays on
      // while that page opens, so nothing posts twice.
      const query = new URLSearchParams({
        service: result.serviceName ?? prompt.service,
        unit: noun,
        value: String(result.value),
        at: result.recordedAt,
        next: result.nextDue ?? '',
      });
      return router.push(`/app/respond/${encodeURIComponent(serviceId)}/thanks?${query.toString()}`);
    }
    setBusy(false);
    if (reply.status === 200 && result?.result === 'outOfRange' && typeof result.value === 'number') {
      setUnsent(null);
      setFlagged({ value: result.value, low: typeof result.low === 'number' ? result.low : prompt.low, high: typeof result.high === 'number' ? result.high : prompt.high });
      return setMode('range');
    }
    if (reply.status === 409 && (result?.result === 'confirmLimit' || result?.result === 'sendNumber')) {
      setUnsent(null);
      setConfirmAllowed(false);
      setNotice({ tone: 'warning', lead: result.result === 'confirmLimit' ? CONFIRM_LIMIT_TEXT : SEND_NUMBER_TEXT });
      return setMode('change');
    }
    setUnsent({ answer, key, offline: typeof navigator !== 'undefined' && navigator.onLine === false });
    return setMode('unsent');
  };

  const banner: Notice | null =
    notice ??
    (mode === 'unsent' && unsent !== null
      ? unsent.offline
        ? { tone: 'offline', lead: 'No signal. Not sent yet.', detail: 'Nothing has been lost. Your number is still here.' }
        : { tone: 'error', lead: 'We could not send that.', detail: 'Your number is still here. Try again, or phone the shift lead.' }
      : null);

  const busyProps = { disabled: busy, 'aria-busy': busy ? ('true' as const) : undefined };

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
          <h1 className={styles.heading}>{`Tell advisors ${prompt.service} is closed?`}</h1>
          <p className={styles.body}>{`Advisors will not be offered ${prompt.service}. It shows as closed on the board until you send a number.`}</p>
        </section>
        <button type="button" className={`${styles.btn} ${styles.primary} ${styles.primaryDark}`} {...busyProps} data-el="REP-APP-CLOSED-CONFIRM-BTN" onClick={() => void send({ kind: 'closed' })}>
          Yes, we are closed
        </button>
        <button type="button" className={`${styles.btn} ${styles.outline}`} disabled={busy} onClick={() => setMode('main')}>
          No, go back
        </button>
        <p className={styles.note}>You can send a number later from the next prompt, or phone the shift lead.</p>
      </>
    );
  } else if (mode === 'range' && flagged !== null) {
    body = (
      <>
        <FigureCard service={prompt.service} figure={flagged.value} unit={prompt.unitLabel} />
        <div className={styles.ask}>
          <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
            <path d="M12 3l10 18H2z" />
            <path d="M12 10v5M12 18.2h.01" />
          </svg>
          <div>
            <p className={styles.askTitle}>{`Is ${flagged.value} right?`}</p>
            <p className={styles.askText}>
              {`That is far ${flagged.value > flagged.high ? 'above' : 'below'} your usual range of ${flagged.low} to ${flagged.high}. If it is right, send it. The shift lead will be told so they can check.`}
            </p>
          </div>
        </div>
        <button type="button" className={`${styles.btn} ${styles.primary}`} {...busyProps} data-el="REP-APP-RANGE-CONFIRM-BTN" onClick={() => void send({ kind: 'number', value: flagged.value })}>
          {`Yes, send ${flagged.value}`}
        </button>
        <button
          type="button"
          className={`${styles.btn} ${styles.outline}`}
          disabled={busy}
          onClick={() => {
            setValue(flagged.value);
            setMode('change');
          }}
        >
          Change the number
        </button>
        <p className={styles.note}>Nothing is recorded until you press a button.</p>
      </>
    );
  } else if (mode === 'unsent' && unsent !== null) {
    const pending = unsent.answer.kind === 'number' ? unsent.answer.value : unsent.answer.kind === 'confirm' ? prompt.recordedValue : null;
    body = (
      <>
        <FigureCard service={prompt.service} figure={pending} unit={prompt.unitLabel}>
          <p>Closed to referrals.</p>
        </FigureCard>
        <span className={`${styles.tag} ${styles.tagDashed}`}>Not sent yet</span>
        <button type="button" className={`${styles.btn} ${styles.primary}`} {...busyProps} data-el="REP-APP-RETRY-BTN" onClick={() => void send(unsent.answer, unsent.key)}>
          Try again now
        </button>
        <p className={styles.note}>Keep this page open. Nothing is recorded until it is sent.</p>
      </>
    );
  } else {
    const changing = mode === 'change' || !recorded;
    const showConfirm = recorded && confirmAllowed && mode === 'main';
    const sendClass = !showConfirm ? `${styles.primary} ${value === null ? styles.off : ''}` : styles.outline;
    body = (
      <>
        <FigureCard
          service={prompt.service}
          label={recorded ? 'Capacity update' : 'First update'}
          replyBy={prompt.replyBy ?? undefined}
          figure={prompt.recordedValue}
          unit={prompt.unitLabel}
          recordedAt={prompt.asOf ?? undefined}
          recordedNote={showConfirm ? 'Still right?' : undefined}
          dataEl="REP-APP-FIGURE"
        >
          <p>{`How many ${noun} can you take${windowText ? ` ${windowText}` : ''}?`}</p>
        </FigureCard>

        {showConfirm ? (
          <button type="button" className={`${styles.btn} ${styles.primary}`} {...busyProps} data-el="REP-APP-CONFIRM-BTN" onClick={() => void send({ kind: 'confirm' })}>
            {`Yes, still ${prompt.recordedValue}`}
          </button>
        ) : null}
        {recorded && !changing ? (
          <button type="button" className={`${styles.btn} ${styles.outline}`} disabled={busy} aria-expanded="false" data-el="REP-APP-DIFFERENT-BTN" onClick={() => setMode('change')}>
            Send a different number
          </button>
        ) : null}

        {changing ? (
          <>
            <div className={`${styles.card} ${styles.cardCentre}`}>
              <NumberStepper
                label={capitalise(prompt.unitLabel)}
                title={recorded ? `New number of ${noun}` : undefined}
                value={value}
                unit={noun}
                usualMin={prompt.low}
                usualMax={prompt.high}
                onChange={setValue}
                dataEl="REP-APP-STEPPER"
              />
            </div>
            <button
              type="button"
              className={`${styles.btn} ${sendClass}`}
              disabled={busy || value === null}
              aria-busy={busy ? 'true' : undefined}
              data-el="REP-APP-SEND-BTN"
              onClick={() => value !== null && void send({ kind: 'number', value })}
            >
              {value === null ? 'Choose a number to send' : `Send ${value}`}
            </button>
          </>
        ) : null}

        {recorded && changing ? (
          <button type="button" className={`${styles.btn} ${styles.dashed} ${styles.plain}`} disabled={busy} onClick={() => setMode('main')}>
            Back
          </button>
        ) : null}
        {!(recorded && changing) ? (
          <button type="button" className={`${styles.btn} ${styles.dashed}`} {...busyProps} data-el="REP-APP-CLOSED-BTN" onClick={() => setMode('closed')}>
            We are closed to referrals
          </button>
        ) : null}

        {nextDueText !== '' ? <p className={styles.note}>{nextDueText}</p> : null}
      </>
    );
  }

  return (
    <main ref={page} className={styles.stack}>
      {banner !== null ? (
        <StateBanner tone={banner.tone} lead={banner.lead} dataEl="REP-APP-NOTICE">
          {banner.detail}
        </StateBanner>
      ) : null}
      {body}
      <p role="status" className={styles.srOnly}>
        {busy ? 'Sending your answer.' : ''}
      </p>
    </main>
  );
}
