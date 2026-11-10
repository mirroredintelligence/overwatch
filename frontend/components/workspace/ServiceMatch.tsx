'use client';

import { useEffect, useState, type ReactElement } from 'react';
import { AGE_BANDS, NEEDS } from '@/lib/advisor/codes';
import { normalisePostcode, outwardCode } from '@/lib/advisor/postcode';
import { checkService } from '@/lib/advisor/v2/browser';
import type { FitCheck } from '@/lib/advisor/v2/check';
import styles from './ServiceCheck.module.css';
import { useWorkspace } from './WorkspaceProvider';

// "Why it matches this patient" (AdvisorService board, DEC-1379): when the advisor arrives at a service with the patient's
// criteria already set, the page checks that one service at once and says why it fits, or why it does not. The back end
// decides (the same rule as the find, DEC-1377); this only shows its answer beside the criteria already in memory. It
// shows nothing when the check fails, never a fit it was not given, and the timeframe is not listed: it is not a
// criterion. Nothing is stored; the criteria go in the body of one POST.

type State = { kind: 'idle' } | { kind: 'checking' } | { kind: 'failed' } | { kind: 'done'; read: FitCheck };

const ageLabel = (code: string | null): string => AGE_BANDS.find((band) => band.code === code)?.label ?? '';
const needLabel = (code: string): string => NEEDS.find((need) => need.code === code)?.label ?? code;

export function ServiceMatch({ serviceId }: { serviceId: string }): ReactElement | null {
  const { criteria, criteriaComplete } = useWorkspace();
  // The criteria as they were when the page opened: a change made in "Book a slot" does not rerun this check.
  const [first] = useState(() => ({ ...criteria, complete: criteriaComplete }));
  const postcode = normalisePostcode(first.postcode);
  const eligible = first.complete && postcode !== null && first.age !== null && first.urgency !== null;
  const [state, setState] = useState<State>({ kind: eligible ? 'checking' : 'idle' });

  useEffect(() => {
    if (!eligible || postcode === null || first.age === null || first.urgency === null) return;
    let live = true;
    void checkService(serviceId, { postcode, ageBand: first.age, needs: first.needs, urgency: first.urgency }).then((read) => {
      if (live) setState(read === null ? { kind: 'failed' } : { kind: 'done', read });
    });
    return () => {
      live = false;
    };
    // Once for the criteria the page opened with.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serviceId]);

  if (state.kind === 'idle' || state.kind === 'failed') return null;
  if (state.kind === 'checking') {
    return (
      <p role="status" className={styles.help}>
        Checking this patient against the service.
      </p>
    );
  }

  const { read } = state;
  const full = normalisePostcode(first.postcode);
  const district = full === null ? null : outwardCode(full);
  return (
    <section className={styles.match} aria-label="Match with this patient">
      <h2 className={styles.heading}>{read.fits ? 'Why it matches this patient' : 'Why it does not match this patient'}</h2>
      {read.fits ? (
        <ul className={styles.matchList}>
          <li>{`Age ${ageLabel(first.age)} · Accepted`}</li>
          <li>{`Need: ${first.needs.map(needLabel).join(', ')} · Accepted`}</li>
          {district === null ? null : <li>{`${district} is inside the coverage area · Covered`}</li>}
        </ul>
      ) : (
        <ul className={styles.matchList} aria-label="Reasons">
          {read.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}
      {read.warnings.length > 0 ? (
        <ul className={styles.matchList} aria-label="Warnings">
          {read.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
