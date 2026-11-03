'use client';

import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { LeadPhonedDialog } from './LeadPhonedDialog';
import { Button } from '@/components/ui/Button';
import { StageArea, StageGrid, StageLayer } from '@/components/ui/StageGrid';
import { CANNOT_DO, leadPost, leadRead } from '@/lib/lead/browser';
import { clockTime } from '@/lib/lead/format';
import styles from './SuspendService.module.css';

// Suspend and resume one service (W42; board "Suspend and resume a service"). A suspension is the shift lead's
// act: the page asks why, says what happens at once, and then shows the suspended view from the answer. The
// back end does not give the suspension state on a read, so a fresh visit shows the suspend form (DEC-657).
// Resuming needs two confirmations, and the call-back to the register number is the lead's own (the service
// is phoned). One pinned card carries the service and a state chip that changes shape and word; the four
// states are layers of one stage, and only the current one can be reached.

type Phase = 'suspend' | 'suspended' | 'resume' | 'resumed';

const PHASES: readonly Phase[] = ['suspend', 'suspended', 'resume', 'resumed'];
const TEMPLATES = PHASES.map(() => '340px minmax(0,1fr) 0px');
const GAPS = PHASES.map(() => '22px');

const REASONS: [string, string][] = [
  ['suspected-false-reports', 'Suspected false reports'],
  ['closed-unexpectedly', 'Closed unexpectedly'],
  ['contact-unreachable', 'Contact cannot be reached'],
  ['other', 'Other'],
];

const HAPPENS: string[] = [
  'The board shows Not updated, phone to confirm.',
  'The service leaves the options.',
  'Prompts stop.',
  'Open requests expire.',
];

type Suspension = { since: string; expiredRequests: number; notified: boolean };

function expiredWords(count: number): string {
  return count === 0 ? 'None expired' : `${count} expired`;
}

export function SuspendService({ serviceId }: { serviceId: string }) {
  const [name, setName] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>('suspend');
  const [reason, setReason] = useState<string | null>(null);
  const [reasonError, setReasonError] = useState(false);
  const [suspension, setSuspension] = useState<Suspension | null>(null);
  const [phoned, setPhoned] = useState(false);
  const [resolved, setResolved] = useState(false);
  const [nextDue, setNextDue] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [phonedDialog, setPhonedDialog] = useState(false);
  const reasonGroupId = useId();
  const headings = useRef<Partial<Record<Phase, HTMLHeadingElement | null>>>({});
  const firstPhase = useRef(true);

  useEffect(() => {
    let cancelled = false;
    void leadRead(`/api/bff/lead/services/${encodeURIComponent(serviceId)}`).then((result) => {
      const body = result.ok ? (result.body as { name?: unknown }) : undefined;
      if (!cancelled && typeof body?.name === 'string') setName(body.name);
    });
    return () => {
      cancelled = true;
    };
  }, [serviceId]);

  // The page opens with focus where it was (never on the confirm button). When the state changes, focus moves
  // to the new state's heading, so the person is told where they are and a stray Enter does nothing.
  useEffect(() => {
    if (firstPhase.current) {
      firstPhase.current = false;
      return;
    }
    headings.current[phase]?.focus();
  }, [phase]);

  const label = name ?? 'this service';
  const stage = PHASES.indexOf(phase);
  const suspendedNow = phase === 'suspended' || phase === 'resume';
  const ready = phoned && resolved;

  async function suspend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setFailure(null);
    if (reason === null) {
      setReasonError(true);
      return;
    }
    setReasonError(false);
    setBusy(true);
    const result = await leadPost(`/api/bff/lead/services/${encodeURIComponent(serviceId)}/suspend`, { reason });
    setBusy(false);
    if (!result.ok) {
      setFailure(result.status === 403 ? CANNOT_DO : 'The service could not be suspended. Try again.');
      return;
    }
    setSuspension(result.body as Suspension);
    setPhase('suspended');
  }

  async function resume() {
    if (!ready || busy) return;
    setFailure(null);
    setBusy(true);
    const result = await leadPost(`/api/bff/lead/services/${encodeURIComponent(serviceId)}/resume`, {
      phonedRegisterNumber: true,
      reasonResolved: true,
    });
    setBusy(false);
    if (!result.ok) {
      setFailure(result.status === 403 ? CANNOT_DO : 'The service could not be resumed. Try again.');
      return;
    }
    const due = (result.body as { nextDueAt?: unknown } | undefined)?.nextDueAt;
    setNextDue(typeof due === 'string' ? due : null);
    setPhase('resumed');
  }

  function startAgain() {
    setReason(null);
    setReasonError(false);
    setSuspension(null);
    setPhoned(false);
    setResolved(false);
    setNextDue(null);
    setFailure(null);
    setPhase('suspend');
  }

  function backToSuspended() {
    setFailure(null);
    setPhase('suspended');
  }

  return (
    <main className={styles.page}>
      <StageGrid stage={stage} templates={TEMPLATES} gaps={GAPS} className={styles.grid}>
        <StageArea name="list">
          <section className={styles.pinned} aria-label="The service">
            <p className={styles.kicker}>The service</p>
            <p className={styles.serviceName}>{label}</p>
            <span className={styles.chip} data-shape={suspendedNow ? 'square' : 'circle'}>
              <span className={styles.dot} aria-hidden="true" />
              {suspendedNow ? 'Suspended' : 'Reporting'}
            </span>
            <p className={styles.chipNote}>
              {suspendedNow
                ? 'Out of the options. The board shows Not updated, phone to confirm.'
                : 'In the options and reporting as usual.'}
            </p>
          </section>
        </StageArea>

        <StageArea name="stage">
          <StageLayer index={0} current={stage}>
            <form onSubmit={(event) => void suspend(event)} noValidate className={styles.panel}>
              <h1 ref={(el) => void (headings.current.suspend = el)} tabIndex={-1} className={styles.heading}>
                {`Suspend ${label}`}
              </h1>
              <div className={styles.what}>
                <p className={styles.whatHeading}>What happens at once</p>
                <ul aria-label="What happens at once">
                  {HAPPENS.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </div>
              <fieldset
                role="radiogroup"
                className={styles.group}
                aria-describedby={reasonError ? `${reasonGroupId}-error` : undefined}
              >
                <legend className={styles.legend}>Why?</legend>
                {reasonError ? (
                  <p id={`${reasonGroupId}-error`} role="alert" className={styles.error}>
                    Choose why
                  </p>
                ) : null}
                <div className={styles.options}>
                  {REASONS.map(([value, text]) => (
                    <label key={value} className={styles.opt}>
                      <input
                        type="radio"
                        name="suspend-reason"
                        value={value}
                        checked={reason === value}
                        onChange={() => setReason(value)}
                        data-el={`LEAD-SUSPEND-REASON-${value.toUpperCase()}`}
                      />
                      <span className={styles.box} aria-hidden="true">
                        {reason === value ? '✓' : ''}
                      </span>
                      {text}
                    </label>
                  ))}
                </div>
              </fieldset>
              {failure && phase === 'suspend' ? (
                <p role="alert" className={styles.error}>
                  {failure}
                </p>
              ) : null}
              <div className={styles.actions}>
                <button type="submit" className={styles.danger} disabled={busy} aria-busy={busy ? 'true' : undefined} data-el="LEAD-SUSPEND-BTN">
                  {`Suspend ${label}`}
                </button>
                <a className={styles.quiet} href="/lead">
                  Cancel
                </a>
              </div>
            </form>
          </StageLayer>

          <StageLayer index={1} current={stage}>
            <div className={styles.panel}>
              <h1 ref={(el) => void (headings.current.suspended = el)} tabIndex={-1} className={styles.heading}>
                {`${label} is suspended`}
              </h1>
              {suspension !== null ? (
                <dl className={styles.facts}>
                  <div className={styles.fact}>
                    <dt>Since</dt>
                    <dd>{clockTime(suspension.since)}</dd>
                  </div>
                  <div className={styles.fact}>
                    <dt>Open requests</dt>
                    <dd>{expiredWords(suspension.expiredRequests)}</dd>
                  </div>
                  <div className={styles.fact}>
                    <dt>The service was</dt>
                    <dd>{suspension.notified ? 'Told by text' : 'Not told by text'}</dd>
                  </div>
                </dl>
              ) : null}
              <p className={styles.lead}>
                Resuming needs a call-back, so you know you are speaking to the right people. Phone them, then resume.
              </p>
              <p className={styles.note}>The register number is not on this screen yet.</p>
              <div className={styles.actions}>
                <Button variant="secondary" onClick={() => setPhonedDialog(true)} dataEl="LEAD-SUSPEND-PHONED-BTN">
                  Phone the service
                </Button>
                <Button variant="primary" onClick={() => setPhase('resume')} dataEl="LEAD-RESUME-BTN">
                  Resume the service
                </Button>
              </div>
            </div>
          </StageLayer>

          <StageLayer index={2} current={stage}>
            <div className={styles.panel}>
              <h1 ref={(el) => void (headings.current.resume = el)} tabIndex={-1} className={styles.heading}>
                {`Before you resume ${label}`}
              </h1>
              <fieldset className={styles.group}>
                <legend className={styles.legend}>Both are needed</legend>
                <div className={`${styles.options} ${styles.stacked}`}>
                  <label className={styles.opt} data-tone="primary">
                    <input type="checkbox" checked={phoned} onChange={(e) => setPhoned(e.target.checked)} />
                    <span className={styles.box} aria-hidden="true">
                      {phoned ? '✓' : ''}
                    </span>
                    I phoned the service on the register number
                  </label>
                  <label className={styles.opt} data-tone="primary">
                    <input type="checkbox" checked={resolved} onChange={(e) => setResolved(e.target.checked)} />
                    <span className={styles.box} aria-hidden="true">
                      {resolved ? '✓' : ''}
                    </span>
                    The reason is resolved
                  </label>
                </div>
              </fieldset>
              <p className={styles.note}>Resuming is logged with who and when.</p>
              {failure && phase === 'resume' ? (
                <p role="alert" className={styles.error}>
                  {failure}
                </p>
              ) : null}
              <div className={styles.actions}>
                <Button
                  variant="primary"
                  disabled={!ready}
                  busy={busy}
                  onClick={() => void resume()}
                  dataEl="LEAD-RESUME-CONFIRM-BTN"
                >
                  Resume the service
                </Button>
                <button type="button" className={styles.quiet} onClick={backToSuspended}>
                  Cancel
                </button>
              </div>
            </div>
          </StageLayer>

          <StageLayer index={3} current={stage}>
            <div className={`${styles.panel} ${styles.panelDone}`}>
              <div className={styles.tick} aria-hidden="true">
                <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="var(--c-primary)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M5 12.5l4.5 4.5L19 7.5" />
                </svg>
              </div>
              <h1 ref={(el) => void (headings.current.resumed = el)} tabIndex={-1} className={styles.backTitle}>
                {`${label} is back`}
              </h1>
              <p className={styles.leadBig}>
                {`It returns to the options once it reports. Prompts start again at the next due time.${nextDue !== null ? ` Next report due ${clockTime(nextDue)}.` : ''} The resume is logged with your name and the time.`}
              </p>
              <div className={styles.actionsBare}>
                <Button variant="primary" href="/lead">
                  Back to the shift
                </Button>
                <button type="button" className={styles.quiet} onClick={startAgain}>
                  Start again
                </button>
              </div>
            </div>
          </StageLayer>
        </StageArea>
        <StageArea name="side" />
      </StageGrid>

      <p role="status" className={styles.srOnly}>
        {phase === 'resumed' ? `${label} is back` : ''}
      </p>
      <LeadPhonedDialog open={phonedDialog} serviceId={serviceId} serviceName={label} onClose={() => setPhonedDialog(false)} />
    </main>
  );
}
