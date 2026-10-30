'use client';

import { useEffect, useRef, useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { bffFetch } from '@/lib/advisor/browser';
import type { OptionsParts } from '@/lib/advisor/options';
import { NotSuitableList } from './NotSuitableList';
import { ServiceCard } from './ServiceCard';
import styles from './OptionsList.module.css';

// The options for a case (W13): the services that meet the hard criteria, in the order the back end
// sent them, never ranked. The list is read once per page load: the back end writes an audit snapshot
// for each read, so a focus or a re-render must not read again.

export type OptionsListProps = {
  caseId: string;
  onRequest?: (serviceId: string) => void;
  onCriteria?: (serviceId: string) => void;
  onPhoned?: (serviceId: string) => void;
  /** Wired by the clinical escalation task (W45). Until then the button does nothing. */
  onAskClinical?: () => void;
};

type Load = { kind: 'loading' } | { kind: 'ready'; parts: OptionsParts } | { kind: 'failed' };

const READ_ONLY_BODY = 'You cannot book or change these services from here. Phone the service to check.';

function headingFor(count: number): string {
  return count === 1 ? "1 service meets this patient's criteria" : `${count} services meet this patient's criteria`;
}

export function OptionsList({ caseId, onRequest, onCriteria, onPhoned, onAskClinical }: OptionsListProps) {
  const [load, setLoad] = useState<Load>({ kind: 'loading' });
  const requested = useRef<string | null>(null);

  useEffect(() => {
    // One read per case. Re-running the effect (a strict-mode remount) does not read again.
    if (requested.current === caseId) return;
    requested.current = caseId;
    bffFetch<OptionsParts>(`/api/bff/cases/${encodeURIComponent(caseId)}/options`).then((reply) => {
      setLoad(reply.ok ? { kind: 'ready', parts: reply.body } : { kind: 'failed' });
    });
  }, [caseId]);

  if (load.kind === 'loading') return <p>Loading the options.</p>;
  if (load.kind === 'failed') return <p role="alert">The options could not be read. Try again.</p>;

  const { options, notSuitable } = load.parts;
  const hasNetwork = options.some((option) => option.network !== null);

  return (
    <section className={styles.list} aria-label="Options">
      {options.length === 0 ? (
        <h2 className={styles.heading}>No service fits right now</h2>
      ) : (
        <>
          <h2 className={styles.heading}>{headingFor(options.length)}</h2>
          <p className={styles.sub}>Sorted by travel time. Not ranked.</p>
          {hasNetwork ? <Banner tone="info" title="Read only">{READ_ONLY_BODY}</Banner> : null}
          <div className={styles.cards}>
            {options.map((option) => (
              <ServiceCard
                key={option.serviceId}
                option={option}
                onRequest={onRequest}
                onCriteria={onCriteria}
                onPhoned={onPhoned}
              />
            ))}
          </div>
        </>
      )}

      <NotSuitableList items={notSuitable} />

      <footer className={styles.footer}>
        <p className={styles.note}>No patient name is stored. Postcode and needs are cleared after the call record closes.</p>
        <div className={styles.actions}>
          <Button variant="secondary" dataEl="ADV-OPT-CLINICAL-BTN" onClick={() => onAskClinical?.()}>
            Ask clinical advisor
          </Button>
          <Button variant="neutral" href={`/advisor/case/${encodeURIComponent(caseId)}/finish`}>
            Record outcome
          </Button>
          <Button variant="neutral" href={`/advisor/case/${encodeURIComponent(caseId)}/finish#summary`}>
            Copy summary for SystmOne
          </Button>
        </div>
      </footer>
    </section>
  );
}
