'use client';

import { useEffect, useRef, useState } from 'react';
import { bffFetch } from '@/lib/advisor/browser';
import type { CaseView } from '@/lib/advisor/codes';
import type { OptionsParts } from '@/lib/advisor/options';
import { AskClinicalPanel } from './AskClinicalPanel';
import { OptionsMap } from './OptionsMap';
import { OutOfArea, PostcodeNotFound } from './PostcodeStates';
import { ViewToggle } from './ViewToggle';
import styles from './map.module.css';

// The map view of the options (W50). It reads the same options as the list, once per load, and the
// case for its postcode. A postcode that is not found, or outside the area, gets its own state.

type Load =
  | { kind: 'loading' }
  | { kind: 'ready'; parts: OptionsParts; postcode: string | null }
  | { kind: 'failed' };

export function MapScreen({ caseId }: { caseId: string }) {
  const [load, setLoad] = useState<Load>({ kind: 'loading' });
  const [selected, setSelected] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const requested = useRef<string | null>(null);
  const id = encodeURIComponent(caseId);

  useEffect(() => {
    if (requested.current === caseId) return;
    requested.current = caseId;
    Promise.all([
      bffFetch<OptionsParts>(`/api/bff/cases/${id}/options`),
      bffFetch<CaseView>(`/api/bff/cases/${id}`),
    ]).then(([options, caseRead]) => {
      if (!options.ok) {
        setLoad({ kind: 'failed' });
        return;
      }
      setLoad({ kind: 'ready', parts: options.body, postcode: caseRead.ok ? caseRead.body.postcode : null });
    });
  }, [caseId, id]);

  if (load.kind === 'loading') return <p>Loading the map.</p>;
  if (load.kind === 'failed') return <p role="alert">The map could not be read. Try again.</p>;

  const { parts, postcode } = load;
  // "Ask a clinical advisor" (W45): a postcode the map cannot place is one of the states that offers it.
  const ask = asking ? <AskClinicalPanel caseRef={caseId} optionsShown={0} onClose={() => setAsking(false)} /> : null;
  if (parts.notFound) {
    return (
      <>
        <PostcodeNotFound caseId={caseId} onAskClinical={() => setAsking(true)} />
        {ask}
      </>
    );
  }
  if (parts.outOfArea) {
    return (
      <>
        <OutOfArea caseId={caseId} postcode={postcode ?? ''} onAskClinical={() => setAsking(true)} />
        {ask}
      </>
    );
  }

  const place = postcode ?? 'this patient';
  return (
    <section className={styles.screen} aria-label="Map">
      <ViewToggle caseId={caseId} current="map" />
      <h2 className={styles.heading}>{`Options near ${place}`}</h2>
      <p className={styles.sub}>Same services as the list. Sorted by travel time. Not ranked.</p>
      <OptionsMap
        caseId={caseId}
        postcode={place}
        patientArea={parts.patientArea}
        options={parts.options}
        selectedId={selected}
        onSelect={(serviceId) => setSelected(serviceId)}
      />
    </section>
  );
}
