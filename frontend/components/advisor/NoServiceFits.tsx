'use client';

import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { bffFetch } from '@/lib/advisor/browser';
import type { CaseView } from '@/lib/advisor/codes';
import styles from './NoServiceFits.module.css';

// The state when no service fits (W16). It always offers a next step: the time can be widened (when
// the case was within 2 hrs), a service can be phoned from the board, the outcome can be recorded
// under local protocol, or a clinical advisor can be asked. A refusal never ends the call.

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
    // The case is saved whole: every field as it was read, with the urgency changed to today.
    const reply = await bffFetch<CaseView>(`/api/bff/cases/${id}`, {
      method: 'PUT',
      body: {
        referrerType: view.referrerType,
        ageBand: view.ageBand,
        postcode: view.postcode,
        needs: view.needs,
        urgency: 'today',
        scores: view.scores,
      },
      ifMatch: view.etag ?? undefined,
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

  return (
    <section className={styles.screen} aria-labelledby="no-fit-heading">
      <h2 id="no-fit-heading" className={styles.heading}>
        No service fits right now
      </h2>
      <p className={styles.sub}>Every service is either not accepting, outside the criteria, or not updated.</p>
      <a className={styles.back} href={`/advisor/case/${id}`}>
        Back to needs
      </a>

      <h3 className={styles.instead}>What instead</h3>
      <div className={styles.options}>
        {canWiden ? (
          <Button variant="secondary" busy={busy} dataEl="ADV-NOFIT-WIDEN-BTN" onClick={widen}>
            Widen the time: today instead of within 2 hrs
          </Button>
        ) : null}
        <Button variant="secondary" href="/advisor/board" dataEl="ADV-NOFIT-PHONE-LINK">
          Phone a service you know has space
        </Button>
        <Button variant="secondary" href={`/advisor/case/${id}/finish?outcome=no-service-fits`} dataEl="ADV-NOFIT-OTHER-BTN">
          Other routes under local protocol
        </Button>
        <Button variant="primary" dataEl="ADV-NOFIT-CLINICAL-BTN" onClick={() => onAskClinical()}>
          Ask a clinical advisor
        </Button>
      </div>

      {failed ? (
        <p role="alert" className={styles.error}>
          {WIDEN_FAILED}
        </p>
      ) : null}
      <p className={styles.note}>Never end the call on a refusal. Always offer a next step.</p>
    </section>
  );
}
