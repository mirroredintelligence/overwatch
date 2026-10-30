'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { bffFetch } from '@/lib/advisor/browser';
import type { OptionsParts } from '@/lib/advisor/options';
import { AskClinicalPanel } from './AskClinicalPanel';
import { CriteriaDialog } from './CriteriaDialog';
import { DeclinedDialog } from './DeclinedDialog';
import { NoServiceFits } from './NoServiceFits';
import { ViewToggle } from './ViewToggle';
import { NotSuitableList } from './NotSuitableList';
import { PhonedDialog } from './PhonedDialog';
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
  /** Called when the advisor asks for clinical advice; the dialog itself is opened here (W45). */
  onAskClinical?: () => void;
};

type Load = { kind: 'loading' } | { kind: 'ready'; parts: OptionsParts } | { kind: 'failed' };

const READ_ONLY_BODY = 'You cannot book or change these services from here. Phone the service to check.';

function headingFor(count: number): string {
  return count === 1 ? "1 service meets this patient's criteria" : `${count} services meet this patient's criteria`;
}

type Open = { kind: 'criteria' | 'phoned' | 'declined'; serviceId: string; serviceName: string };

export function OptionsList({ caseId, onRequest, onCriteria, onPhoned, onAskClinical }: OptionsListProps) {
  const [load, setLoad] = useState<Load>({ kind: 'loading' });
  const [open, setOpen] = useState<Open | null>(null);
  const [asking, setAsking] = useState(false);
  const requested = useRef<string | null>(null);

  // Reads the options. Called once per case on mount, and again only after a saved answer, so the
  // list shows what the answer changed. Never on focus.
  const readOptions = useCallback(async () => {
    const reply = await bffFetch<OptionsParts>(`/api/bff/cases/${encodeURIComponent(caseId)}/options`);
    setLoad(reply.ok ? { kind: 'ready', parts: reply.body } : { kind: 'failed' });
  }, [caseId]);

  useEffect(() => {
    // One read per case. Re-running the effect (a strict-mode remount) does not read again.
    if (requested.current === caseId) return;
    requested.current = caseId;
    void readOptions();
  }, [caseId, readOptions]);

  if (load.kind === 'loading') return <p>Loading the options.</p>;
  if (load.kind === 'failed') return <p role="alert">The options could not be read. Try again.</p>;

  const { options, notSuitable } = load.parts;
  const hasNetwork = options.some((option) => option.network !== null);
  const close = () => setOpen(null);
  // "Ask a clinical advisor" (W45): this list owns the dialog, so the button and the no-fit state share it.
  const askClinical = () => {
    setAsking(true);
    onAskClinical?.();
  };
  const opener = (kind: Open['kind']) => (serviceId: string) => {
    const name = options.find((option) => option.serviceId === serviceId)?.name ?? '';
    setOpen({ kind, serviceId, serviceName: name });
  };

  return (
    <section className={styles.list} aria-label="Options">
      <ViewToggle caseId={caseId} current="list" />
      {options.length === 0 ? (
        <NoServiceFits caseId={caseId} onWidened={() => void readOptions()} onAskClinical={askClinical} />
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
                onCriteria={(id) => {
                  opener('criteria')(id);
                  onCriteria?.(id);
                }}
                onPhoned={(id) => {
                  opener('phoned')(id);
                  onPhoned?.(id);
                }}
                onDeclined={opener('declined')}
              />
            ))}
          </div>
        </>
      )}

      {open?.kind === 'criteria' ? (
        <CriteriaDialog serviceId={open.serviceId} serviceName={open.serviceName} onClose={close} />
      ) : null}
      {open?.kind === 'phoned' ? (
        <PhonedDialog
          caseRef={caseId}
          serviceId={open.serviceId}
          serviceName={open.serviceName}
          onSaved={() => void readOptions()}
          onClose={close}
        />
      ) : null}
      {open?.kind === 'declined' ? (
        <DeclinedDialog
          caseRef={caseId}
          serviceId={open.serviceId}
          serviceName={open.serviceName}
          onSaved={() => void readOptions()}
          onClose={close}
        />
      ) : null}

      {asking ? <AskClinicalPanel caseRef={caseId} optionsShown={options.length} onClose={() => setAsking(false)} /> : null}

      <NotSuitableList items={notSuitable} />

      {options.length === 0 ? null : (
        <footer className={styles.footer}>
          <p className={styles.note}>No patient name is stored. Postcode and needs are cleared after the call record closes.</p>
          <div className={styles.actions}>
            <Button variant="secondary" dataEl="ADV-OPT-CLINICAL-BTN" onClick={askClinical}>
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
      )}
    </section>
  );
}
