'use client';

import { useEffect, useId, useState } from 'react';
import { bffFetch, newIdempotencyKey } from '@/lib/advisor/browser';
import type { CaseView } from '@/lib/advisor/codes';
import styles from './NoServiceFits.module.css';

// The state when no service fits (W16). It always offers a next step: the time can be widened (when
// the case was within 2 hrs), a service can be phoned from the board, a clinical advisor can be asked,
// or the outcome can be recorded under local protocol. A refusal never ends the call.

const WIDEN_FAILED = 'The time could not be changed. Try again.';

export type NoServiceFitsProps = {
  caseId: string;
  /** Called after the time is widened, so the options are read again. */
  onWidened: () => void;
  /** Wired by the clinical escalation task (W45). Until then the button does nothing. */
  onAskClinical: () => void;
};

export function NoServiceFits({ caseId, onWidened, onAskClinical }: NoServiceFitsProps) {
  const [view, setView] = useState<CaseView | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const id = encodeURIComponent(caseId);

  useEffect(() => {
    let live = true;
    bffFetch<CaseView>(`/api/bff/cases/${id}`).then((reply) => {
      if (live && reply.ok) setView(reply.body);
    });
    return () => {
      live = false;
    };
  }, [id]);

  // The widen option is offered only for a case that is within 2 hrs; it is not offered otherwise.
  const canWiden = view?.urgency === 'within-2-hrs';

  async function widen() {
    if (view === null || busy) return;
    setBusy(true);
    setFailed(false);
    // The case is saved whole: every field as it was read, with the urgency changed to today. The postcode
    // is left out, so the district on record stays (DEC-398), and the recorded scores are repeated
    // (the back end refuses a change to them).
    const reply = await bffFetch<CaseView>(`/api/bff/cases/${id}`, {
      method: 'PUT',
      body: {
        referrerType: view.referrerType,
        ageBand: view.ageBand,
        needs: view.needs,
        urgency: 'today',
        scores: view.scores,
      },
      ifMatch: view.etag ?? undefined,
      idempotencyKey: newIdempotencyKey(),
    });
    if (reply.ok) {
      setView(reply.body);
      setBusy(false);
      onWidened();
      return;
    }
    setBusy(false);
    setFailed(true);
  }

  // The first step offered is the one the board marks as the way on.
  const firstStep = canWiden ? 'widen' : 'phone';

  return (
    <section className={styles.screen} aria-labelledby="no-fit-heading">
      <a className={styles.back} href={`/advisor/case/${id}`}>
        Back to needs
      </a>

      <div className={styles.intro}>
        <h2 id="no-fit-heading" className={styles.heading}>
          No service fits right now
        </h2>
        <p className={styles.sub}>
          Every service is either not accepting, outside the criteria, or not updated. That is the board&apos;s answer,
          not the end of the call. Choose what to do next.
        </p>
      </div>

      <div role="group" aria-label="What instead" className={styles.steps}>
        {canWiden ? (
          <NextStep
            title="Widen the time: today instead of within 2 hrs"
            line="Reads the options again with the new time. You can change it back."
            first={firstStep === 'widen'}
            dataEl="ADV-NOFIT-WIDEN-BTN"
            busy={busy}
            onClick={widen}
          />
        ) : null}
        <NextStep
          title="Phone a service you know has space"
          line="Then record what they told you, so the board is right for everyone."
          first={firstStep === 'phone'}
          dataEl="ADV-NOFIT-PHONE-LINK"
          href="/advisor/board"
        />
        <NextStep
          title="Ask a clinical advisor"
          line="The case summary goes with the call. No name is sent."
          first={false}
          dataEl="ADV-NOFIT-CLINICAL-BTN"
          onClick={() => onAskClinical()}
        />
        <NextStep
          title="Other routes under local protocol"
          line="For example the emergency route."
          first={false}
          dataEl="ADV-NOFIT-OTHER-BTN"
          href={`/advisor/case/${id}/finish?outcome=no-service-fits`}
        />
      </div>

      {failed ? (
        <p role="alert" className={styles.error}>
          {WIDEN_FAILED}
        </p>
      ) : null}
    </section>
  );
}

type NextStepProps = {
  title: string;
  /** The board's line under the title. It is the step's description, not part of its name. */
  line: string;
  first: boolean;
  dataEl: string;
  href?: string;
  busy?: boolean;
  onClick?: () => void;
};

// One large next-step row: the title is its name, the line is its description, and the arrow is decoration.
function NextStep({ title, line, first, dataEl, href, busy = false, onClick }: NextStepProps) {
  const titleId = useId();
  const lineId = useId();
  const className = first ? `${styles.step} ${styles.first}` : styles.step;
  const content = (
    <>
      <span className={styles.stepText}>
        <span id={titleId} className={styles.stepTitle}>
          {title}
        </span>
        <span id={lineId} className={styles.stepLine}>
          {line}
        </span>
      </span>
      <span className={styles.arrow} aria-hidden="true">
        ›
      </span>
    </>
  );

  if (href !== undefined) {
    return (
      <a
        className={className}
        href={href}
        data-el={dataEl}
        aria-labelledby={titleId}
        aria-describedby={lineId}
      >
        {content}
      </a>
    );
  }
  return (
    <button
      type="button"
      className={className}
      disabled={busy}
      aria-busy={busy ? 'true' : undefined}
      onClick={onClick}
      data-el={dataEl}
      aria-labelledby={titleId}
      aria-describedby={lineId}
    >
      {content}
    </button>
  );
}
