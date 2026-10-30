'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { AdviceForm } from '@/components/clinical/AdviceForm';
import { Button } from '@/components/ui/Button';
import { bffRequest } from '@/lib/bff/browser';
import { londonTime } from '@/lib/board/format';
import { ADVICE_LABELS, REASON_LABELS } from '@/lib/clinical/advice';
import { minutesLeft } from '@/lib/clinical/countdown';
import { summaryLine, urgencyText, WHY_TEXT } from '@/lib/clinical/queue';
import { advisorContactFromJson, seenLineText, type AdvisorContact, type Seen } from '@/lib/clinical/seen';
import type { ClinicalRequest } from '@/lib/clinical/task';
import styles from '@/components/exec/Exec.module.css';

// One taken request (W44, ClinicalAdvisor screens 5 to 7), shown from the back end's read of it
// (DEC-774). The advice form is offered ONLY when that read loaded, carries the case's details and the
// request is held by this clinician (DEC-855, H-375): otherwise the screen says what is missing and
// gives no way to advise. The case is shown as the advisor recorded it: age band, needs, urgency and
// NEWS2 (the postcode is never sent to a clinician, DEC-396). What the advisor saw is its own read (W9G) and
// is shown beside it, capacity only; the advice form does not wait on it, but the call to the advisor is
// offered whenever the request is held. The advisor's number is asked for only when the button is pressed, is
// kept in this component's memory only and goes when the advice is sent.

const BACK = (
  <Link href="/clinical/requests" className={styles.backLink} data-el="CLIN-BACK-LINK">Back to the queue</Link>
);

function Countdown({ returnsAt }: { returnsAt: string }) {
  const [now, setNow] = useState(() => new Date().toISOString());
  // A clock: the minutes left are re-read once a minute, not every second, so a screen reader is not flooded.
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date().toISOString()), 60_000);
    return () => clearInterval(timer);
  }, []);
  const minutes = minutesLeft(returnsAt, now);
  return (
    <p role="status" className={styles.footer}>
      {minutes > 0 ? `Returns to the queue in ${minutes} min` : 'Returns to the queue now'}
    </p>
  );
}

const SEEN_FAILED = 'What the advisor saw could not be read. Phone the advisor to ask.';

function SawSection({ seen }: { seen: Seen | null }) {
  if (seen === null || seen.state === 'unreadable') {
    return <p role="alert" className={styles.error}>{SEEN_FAILED}</p>;
  }
  if (seen.state === 'none' || seen.shownAt === null) {
    return (
      <section className={styles.section} aria-labelledby="case-saw">
        <h2 id="case-saw" className={styles.cardTitle}>What the advisor saw</h2>
        <p>No options display is recorded for this request.</p>
      </section>
    );
  }
  const heading = `What the advisor saw at ${londonTime(seen.shownAt)}`;
  return (
    <section className={styles.section} aria-labelledby="case-saw">
      <h2 id="case-saw" className={styles.cardTitle}>{heading}</h2>
      {seen.noneFitted ? <p>None of the services fitted this case when the advisor asked.</p> : null}
      <ul>
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
    <div className={styles.stack}>
      <div className={styles.actions}>
        <Button variant="secondary" busy={state.kind === 'loading'} onClick={call} dataEl="CLIN-CASE-CALL-BTN">Call the advisor</Button>
      </div>
      {state.kind === 'number' ? (
        <p role="status" aria-label="The advisor’s number"><AdvisorNumber contact={state.contact} /></p>
      ) : null}
      {state.kind === 'lost' ? <p role="alert" className={styles.error}>You no longer hold this request, so the advisor’s number is not shown.</p> : null}
      {state.kind === 'failed' ? <p role="alert" className={styles.error}>The number could not be read. Try again.</p> : null}
    </div>
  );
}

function Unavailable({ message }: { message: string }) {
  return (
    <div className={styles.stack}>
      <p role="alert" className={styles.error}>{message}</p>
      <div className={styles.actions}>{BACK}</div>
    </div>
  );
}

export function CaseView({ requestId, request, seen }: { requestId: string; request: ClinicalRequest | null; seen: Seen | null }) {
  const router = useRouter();
  const [sent, setSent] = useState(false);
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

  const why = WHY_TEXT[request.why] ?? request.why;
  const caseSection = (
    <>
      <h1 className={styles.heading}>{`Case ${request.glance.caseReference}`}</h1>
      <section className={styles.section} aria-labelledby="case-the-case">
        <h2 id="case-the-case" className={styles.cardTitle}>The case</h2>
        {line !== '' ? <p>{line}</p> : <p>The advisor has recorded no details yet.</p>}
        <p>{`Needed: ${urgencyText(request.urgency)}`}</p>
      </section>
      <section className={styles.section} aria-labelledby="case-why">
        <h2 id="case-why" className={styles.cardTitle}>Why the advisor asked</h2>
        <p>{why}</p>
      </section>
    </>
  );

  if (request.status === 'completed') {
    const given = request.advice;
    return (
      <div className={styles.stack}>
        {caseSection}
        <SawSection seen={seen} />
        <section className={styles.section} aria-label="Advice">
          <p>{`Advice given: ${given === null ? 'not recorded' : given.choice in ADVICE_LABELS ? ADVICE_LABELS[given.choice as keyof typeof ADVICE_LABELS] : given.choice}`}</p>
          {given?.reason ? <p>{`Reason: ${given.reason in REASON_LABELS ? REASON_LABELS[given.reason as keyof typeof REASON_LABELS] : given.reason}`}</p> : null}
        </section>
        <div className={styles.actions}>{BACK}</div>
      </div>
    );
  }

  if (request.status === 'requested') {
    return (
      <div className={styles.stack}>
        {caseSection}
        <p>This request is back in the queue. Take it again from the queue to answer it.</p>
        <div className={styles.actions}>{BACK}</div>
      </div>
    );
  }

  return (
    <div className={styles.stack}>
      {caseSection}
      {sent ? null : <SawSection seen={seen} />}
      {sent || request.returnsAt === null ? null : <Countdown returnsAt={request.returnsAt} />}
      {sent ? null : <CallAdvisor requestId={requestId} />}
      {sent ? (
        <section className={styles.section} aria-labelledby="advice-sent">
          <h2 id="advice-sent" className={styles.heading}>Advice sent</h2>
          <p>The advisor has it now. Logged for audit: your role, the time, your advice and what you saw.</p>
          <p className={styles.footer}>Clinical overrides are reviewed with the service leads, not used to assess advisors.</p>
          <div className={styles.actions}>
            <Link href="/clinical/requests" className={styles.backLink} data-el="CLIN-NEXT-BTN">Next request</Link>
            <Button variant="secondary" busy={busy} onClick={offDuty} dataEl="CLIN-OFFDUTY-BTN">Go off duty</Button>
          </div>
        </section>
      ) : (
        <section className={styles.section} aria-labelledby="advice-heading">
          <h2 id="advice-heading" className={styles.heading}>Give advice</h2>
          <AdviceForm requestId={requestId} onSent={() => setSent(true)} />
        </section>
      )}
    </div>
  );
}
