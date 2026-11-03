'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { bffFetch } from '@/lib/advisor/browser';
import type { TextOutcome } from '@/lib/advisor/outcome';
import type { SummaryView } from '@/lib/advisor/summary';
import { CallClosed } from './CallClosed';
import { OutcomeForm } from './OutcomeForm';
import { SummaryCopy } from './SummaryCopy';
import styles from './finish.module.css';

// The finish screen (W15): the outcome, then the summary to copy. When the outcome is saved the case
// is closed and this screen forgets the summary (the postcode and needs), so they are gone from the
// page as well as from the state. The closed state is the same address with ?closed=1, replaced
// rather than pushed, so Back does not return to the form.

type Props = { caseId: string; preselect: TextOutcome | null; closed?: boolean };

export function FinishScreen({ caseId, preselect, closed: closedAtAddress = false }: Props) {
  const router = useRouter();
  const [summary, setSummary] = useState<SummaryView | null>(null);
  const [failed, setFailed] = useState(false);
  const [closed, setClosed] = useState(closedAtAddress);
  // The case number is kept when the summary is forgotten: it is the one thing the closed screen names.
  const [reference, setReference] = useState<string | null>(null);
  // The service the call went to, once the advisor chooses it: the summary is read again naming it, so the
  // referral that is copied says where the patient went, how it was booked and how old the figure was.
  const [destination, setDestination] = useState<string | null>(null);

  useEffect(() => {
    // A case that was closed at the address has no summary to read: the back end would refuse it.
    if (closed) return;
    let live = true;
    const query = destination === null ? '' : `?destination=${encodeURIComponent(destination)}`;
    bffFetch<SummaryView>(`/api/bff/cases/${encodeURIComponent(caseId)}/summary${query}`).then((reply) => {
      if (!live) return;
      if (reply.ok) {
        setFailed(false);
        setSummary(reply.body);
        setReference(reply.body.reference);
      }
      else if (reply.status === 409 && reply.code === 'closed') setClosed(true);
      else {
        // A summary that could not be read again is not left on screen: it would lack the destination.
        setSummary(null);
        setFailed(true);
      }
    });
    return () => {
      live = false;
    };
  }, [caseId, destination, closed]);

  if (closed) return <CallClosed reference={reference} />;

  // The line under the heading names the destination once the summary has it (the board's "Reference 4821 · UCR West").
  const line =
    reference === null
      ? 'Case number not read yet'
      : destination !== null && summary !== null
        ? `Reference ${reference} · ${summary.destination}`
        : `Reference ${reference}`;

  return (
    <div className={styles.columns}>
      <section aria-label="Outcome" className={styles.card}>
        <h1 className={styles.heading}>Record outcome</h1>
        <p className={styles.reference}>{line}</p>
        <OutcomeForm
          caseId={caseId}
          preselect={preselect}
          onDestinationChange={setDestination}
          onClosed={() => {
            setSummary(null);
            setClosed(true);
            router.replace(`/advisor/case/${encodeURIComponent(caseId)}/finish?closed=1`);
          }}
        />
      </section>
      <div className={styles.side}>
        {summary !== null ? <SummaryCopy summary={summary} /> : null}
        {summary === null && failed ? (
          <section className={styles.card}>
            <p role="alert" className={styles.error}>
              The summary could not be read.
            </p>
          </section>
        ) : null}
        {summary === null && !failed ? (
          <section className={styles.card}>
            <p className={styles.text}>Loading the summary.</p>
          </section>
        ) : null}
      </div>
    </div>
  );
}
