'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState, type ReactNode } from 'react';
import { AdviceForm } from '@/components/clinical/AdviceForm';
import { bffRequest } from '@/lib/bff/browser';
import { londonTime } from '@/lib/board/format';
import { AGE_BANDS, labelOf, NEEDS, URGENCIES } from '@/lib/advisor/codes';
import { adviceText, REASON_LABELS } from '@/lib/clinical/advice';
import { minutesLeft } from '@/lib/clinical/countdown';
import { summaryLine, urgencyText, WHY_TEXT } from '@/lib/clinical/queue';
import { advisorContactFromJson, seenLineText, type AdvisorContact, type Seen } from '@/lib/clinical/seen';
import type { ClinicalRequest, Glance } from '@/lib/clinical/task';
import styles from './CaseView.module.css';

// One taken request (W44, ClinicalAdvisor screens 5 to 7), shown from the back end's read of it
// (DEC-774) in three columns: the queue, small; the case; the advice. The advice form is offered ONLY
// when that read loaded, carries the case's details and the request is held by this clinician (DEC-855,
// H-375): otherwise the screen says what is missing and gives no way to advise. The case is shown as the
// advisor recorded it: age band, needs, urgency and NEWS2 (the postcode is never sent to a clinician,
// DEC-396). What the advisor saw is its own read (W9G) and is shown beside it, capacity only. The advice
// form is offered only when that read loaded too (DEC-1179, tightening DEC-1036): advice given without
// seeing what the advisor saw can be advice about the wrong services. A request with no display recorded
// is a read that worked ("none recorded"), so it still allows advice. When the read fails the call to the
// advisor is offered, and a way to read it again. The advisor's number is asked for only when the button
// is pressed, is kept in this component's memory only and goes when the advice is sent. After the advice
// is sent the screen is one confirmation card.

const backLink = (
  <Link href="/clinical/requests" className={styles.link} data-el="CLIN-BACK-LINK">Back to the queue</Link>
);

/** The hold, in the board's pill. It is drawn only when the read carries when the request returns. */
function Hold({ returnsAt }: { returnsAt: string }) {
  const [now, setNow] = useState(() => new Date().toISOString());
  // A clock: the minutes left are re-read once a minute, not every second, so a screen reader is not flooded.
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date().toISOString()), 60_000);
    return () => clearInterval(timer);
  }, []);
  const minutes = minutesLeft(returnsAt, now);
  return (
    <p role="status" className={styles.hold}>
      {`You hold this request · ${minutes > 0 ? `Returns to the queue in ${minutes} min` : 'Returns to the queue now'}`}
    </p>
  );
}

/** The read of what the advisor saw failed or cannot be trusted: the form is not offered (DEC-1179). */
const seenFailed = (seen: Seen | null) => seen === null || seen.state === 'unreadable';

const SEEN_FAILED = 'What the advisor saw could not be read, so no advice can be given from here. Phone the advisor to ask, or read it again.';

function SawSection({ seen }: { seen: Seen | null }) {
  if (seen === null || seen.state === 'unreadable') {
    return <p role="alert" className={`${styles.card} ${styles.cardAlert} ${styles.alert}`}>{SEEN_FAILED}</p>;
  }
  if (seen.state === 'none' || seen.shownAt === null) {
    return (
      <section className={`${styles.card} ${styles.panel}`} aria-labelledby="case-saw">
        <h2 id="case-saw" className={styles.panelTitle}>What the advisor saw</h2>
        <p className={styles.seenNote}>No options display is recorded for this request.</p>
      </section>
    );
  }
  const heading = `What the advisor saw at ${londonTime(seen.shownAt)}`;
  return (
    <section className={`${styles.card} ${styles.panel}`} aria-labelledby="case-saw">
      <h2 id="case-saw" className={styles.panelTitle}>{heading}</h2>
      {seen.noneFitted ? <p className={styles.seenNote}>None of the services fitted this case when the advisor asked.</p> : null}
      <ul className={styles.seenList}>
        {seen.lines.map((line, index) => (
          <li key={`${index}-${line.service}`}>{seenLineText(line)}</li>
        ))}
      </ul>
    </section>
  );
}

type CallState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'number'; contact: AdvisorContact }
  | { kind: 'lost' }
  | { kind: 'failed' };

const telHref = (phone: string) => `tel:${phone.replace(/[^0-9+]/g, '')}`;

function AdvisorNumber({ contact }: { contact: AdvisorContact }) {
  if (contact.phone === null) {
    return <>No number is held for the advisor, and this organisation has no advisor line set.</>;
  }
  const link = <a href={telHref(contact.phone)} data-el="CLIN-CASE-CALL-LINK">{contact.phone}</a>;
  if (contact.via === 'advisor-line') {
    return <>The advisor’s own number is not held. Phone the advisor line on {link}.</>;
  }
  return <>Phone {contact.name ?? 'the advisor'} on {link}.</>;
}

// "Call the advisor": asks the back end for the number when pressed (the back end records that it was
// opened, not the number) and shows it here. Nothing is written to storage, the address or a cookie.
function CallAdvisor({ requestId }: { requestId: string }) {
  const [state, setState] = useState<CallState>({ kind: 'idle' });

  const call = async () => {
    setState({ kind: 'loading' });
    const result = await bffRequest<{ contact: unknown }>(`/api/bff/clinical/requests/${encodeURIComponent(requestId)}/advisor-contact`);
    if (!result.ok) {
      setState(result.status === 404 ? { kind: 'lost' } : { kind: 'failed' });
      return;
    }
    try {
      setState({ kind: 'number', contact: advisorContactFromJson(result.data.contact) });
    } catch {
      setState({ kind: 'failed' });
    }
  };

  return (
    <>
      <button
        type="button"
        className={styles.call}
        disabled={state.kind === 'loading'}
        aria-busy={state.kind === 'loading' ? 'true' : undefined}
        onClick={call}
        data-el="CLIN-CASE-CALL-BTN"
      >
        Call the advisor
      </button>
      {state.kind === 'number' ? (
        <p role="status" aria-label="The advisor’s number" className={styles.callResult}><AdvisorNumber contact={state.contact} /></p>
      ) : null}
      {state.kind === 'lost' ? <p role="alert" className={styles.errors}>You no longer hold this request, so the advisor’s number is not shown.</p> : null}
      {state.kind === 'failed' ? <p role="alert" className={styles.errors}>The number could not be read. Try again.</p> : null}
    </>
  );
}

function Unavailable({ message }: { message: string }) {
  return (
    <div className={styles.caseColumn}>
      <p role="alert" className={`${styles.card} ${styles.cardAlert} ${styles.alert}`}>{message}</p>
      <div className={styles.backRow}>{backLink}</div>
    </div>
  );
}

/** The case as chips: age band, each need, how soon (the advisor's record; nothing is added). */
function caseChips(glance: Glance): string[] {
  const needs = glance.needs.map((code) => NEEDS.find((need) => need.code === code)?.short ?? code);
  return [labelOf(AGE_BANDS, glance.ageBand), ...needs, labelOf(URGENCIES, glance.caseUrgency)].filter((chip): chip is string => chip !== null && chip !== '');
}

function CaseCard({ request, glance }: { request: ClinicalRequest; glance: Glance }) {
  const chips = caseChips(glance);
  return (
    <div className={`${styles.card} ${styles.caseCard}`}>
      <div className={styles.caseHead}>
        <h1 className={styles.heading}>{`Case ${glance.caseReference}`}</h1>
        <span className={styles.asked}>{`Asked at ${londonTime(request.requestedAt)} by the advisor`}</span>
      </div>
      {chips.length > 0 ? (
        <ul className={styles.chips} aria-label="The case">
          {chips.map((chip, index) => <li key={`${index}-${chip}`} className={styles.chip}>{chip}</li>)}
        </ul>
      ) : (
        <p className={styles.news}>The advisor has recorded no details yet.</p>
      )}
      {glance.news2 === null ? null : <p className={styles.news}>{`NEWS2 ${glance.news2}`}</p>}
      {request.service === null ? null : <p className={styles.askedAbout}>{`The advisor was asking about: ${request.service}`}</p>}
      <p className={styles.small}>No postcode and no name are shown to a clinician.</p>
    </div>
  );
}

function WhyCard({ why }: { why: string }) {
  return (
    <section className={`${styles.card} ${styles.panel}`} aria-labelledby="case-why">
      <h2 id="case-why" className={styles.panelTitle}>Why the advisor asked</h2>
      <p className={styles.why}>{why}</p>
    </section>
  );
}

/** The queue, small, so it is never lost: this request as taken by you, then what is waiting. */
function SlimQueue({ request, queue }: { request: ClinicalRequest; queue: readonly ClinicalRequest[] }) {
  const mine = summaryLine(request.glance);
  return (
    <aside aria-label="Queue" className={styles.queue}>
      <p className={`${styles.label} ${styles.queueLabel}`}>Queue</p>
      <div className={`${styles.card} ${styles.queueCard} ${styles.queueMine}`}>
        <p className={styles.queueWhen}>Taken by you</p>
        <p className={styles.queueLine}>{mine ?? 'The case could not be read.'}</p>
      </div>
      {queue.filter((item) => item.id !== request.id).map((item) => {
        const line = summaryLine(item.glance);
        return (
          <div key={item.id} className={`${styles.card} ${styles.queueCard}`}>
            <p className={styles.queueWhen}><span>{urgencyText(item.urgency)}</span></p>
            <p className={styles.queueLine}>{line ?? 'The case could not be read.'}</p>
          </div>
        );
      })}
      <p className={styles.queueNote}>The queue stays here, small, so you never lose it.</p>
    </aside>
  );
}

function Sent({ advice, busy, onOffDuty }: { advice: string; busy: boolean; onOffDuty: () => void }) {
  return (
    <section className={`${styles.card} ${styles.sent}`} aria-labelledby="advice-sent">
      <div className={styles.sentHead}>
        <span className={styles.tick} aria-hidden="true">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <path d="M5 12.5l4.5 4.5L19 7.5" />
          </svg>
        </span>
        <div>
          <h1 id="advice-sent" className={styles.sentHeading}>Advice sent</h1>
          <p className={styles.sentLead}>The advisor has it now.</p>
        </div>
      </div>
      <div>
        <dl className={styles.kv}>
          <dt>Your advice</dt>
          <dd>{advice}</dd>
        </dl>
        <dl className={styles.kv}>
          <dt>Logged for audit</dt>
          <dd>Your role, the time, your advice and what you saw</dd>
        </dl>
      </div>
      <p className={styles.fineprint}>Clinical overrides are reviewed with the service leads. They are not used to assess advisors.</p>
      <div className={styles.sentActions}>
        <Link href="/clinical/requests" className={styles.next} data-el="CLIN-NEXT-BTN">Next request</Link>
        <button type="button" className={styles.offDuty} disabled={busy} aria-busy={busy ? 'true' : undefined} onClick={onOffDuty} data-el="CLIN-OFFDUTY-BTN">
          Go off duty
        </button>
      </div>
    </section>
  );
}

export function CaseView({
  requestId,
  request,
  seen,
  queue = [],
}: {
  requestId: string;
  request: ClinicalRequest | null;
  seen: Seen | null;
  /** The requests waiting in the queue, for the slim column; none when that read failed or was not made. */
  queue?: readonly ClinicalRequest[];
}) {
  const router = useRouter();
  const [sentAdvice, setSentAdvice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const offDuty = async () => {
    setBusy(true);
    await bffRequest('/api/bff/clinical/presence', { method: 'PUT', body: { presence: 'away' } });
    setBusy(false);
    router.push('/clinical');
  };

  if (request === null) return <Unavailable message="This request could not be read, so it cannot be answered from here." />;
  const line = summaryLine(request.glance);
  if (request.glance === null || line === null) {
    return <Unavailable message="The case could not be read, so no advice can be given from here." />;
  }

  const glance = request.glance;
  const why = WHY_TEXT[request.why] ?? request.why;

  if (request.status === 'completed') {
    const given = request.advice;
    return (
      <div className={styles.caseColumn}>
        <CaseCard request={request} glance={glance} />
        <WhyCard why={why} />
        <SawSection seen={seen} />
        <section className={`${styles.card} ${styles.panel}`} aria-label="Advice">
          <p className={styles.seenNote}>{`Advice given: ${given === null ? 'not recorded' : adviceText(given.choice, request.service)}`}</p>
          {given?.reason ? <p className={styles.seenNote}>{`Reason: ${given.reason in REASON_LABELS ? REASON_LABELS[given.reason as keyof typeof REASON_LABELS] : given.reason}`}</p> : null}
        </section>
        <div className={styles.backRow}>{backLink}</div>
      </div>
    );
  }

  if (request.status === 'requested') {
    return (
      <div className={styles.caseColumn}>
        <CaseCard request={request} glance={glance} />
        <WhyCard why={why} />
        <p className={styles.seenNote}>This request is back in the queue. Take it again from the queue to answer it.</p>
        <div className={styles.backRow}>{backLink}</div>
      </div>
    );
  }

  if (sentAdvice !== null) return <Sent advice={sentAdvice} busy={busy} onOffDuty={offDuty} />;

  const call: ReactNode = <CallAdvisor requestId={requestId} />;
  return (
    <div className={styles.grid}>
      <SlimQueue request={request} queue={queue} />
      <div className={styles.caseColumn}>
        {request.returnsAt === null ? null : <Hold returnsAt={request.returnsAt} />}
        <CaseCard request={request} glance={glance} />
        <WhyCard why={why} />
        <SawSection seen={seen} />
        {seenFailed(seen) ? <div className={styles.backRow}>{backLink}</div> : null}
      </div>
      {seenFailed(seen) ? (
        <section className={`${styles.card} ${styles.advice}`} aria-label="Phone the advisor">
          <div className={styles.buttons}>
            {call}
            <button type="button" className={styles.call} onClick={() => router.refresh()} data-el="CLIN-CASE-REREAD-BTN">Read it again</button>
          </div>
        </section>
      ) : (
        <section className={`${styles.card} ${styles.advice}`} aria-labelledby="advice-heading">
          <h2 id="advice-heading" className={styles.adviceHeading}>Your advice</h2>
          <AdviceForm requestId={requestId} serviceName={request.service} onSent={setSentAdvice} after={call} />
        </section>
      )}
    </div>
  );
}
