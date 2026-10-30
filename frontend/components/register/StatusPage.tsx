'use client';

import { useEffect, useState } from 'react';
import { loadStatus, type RegistrationStatusView } from '@/lib/register/browser';
import { Approved } from './status/Approved';
import { InReview } from './status/InReview';
import { Live } from './status/Live';
import { NeedsChanges } from './status/NeedsChanges';
import { NotApproved } from './status/NotApproved';
import { Reverify } from './status/Reverify';
import styles from './register.module.css';

// The applicant's status after submitting (W27). One screen per state; a status the page does not
// know is shown as the page's failure, never guessed at.

export type StatusPageProps = { registrationId: string };

const LOAD_FAILED = 'We could not load your registration. Try again later.';
const SIGNED_OUT = 'Please sign in again.';

type Load = { kind: 'loading' } | { kind: 'open'; view: RegistrationStatusView } | { kind: 'failed' } | { kind: 'signed-out' };

export function StatusPage({ registrationId }: StatusPageProps) {
  const [load, setLoad] = useState<Load>({ kind: 'loading' });

  useEffect(() => {
    let alive = true;
    void loadStatus(registrationId).then((outcome) => {
      if (!alive) return;
      if (outcome.kind === 'open') setLoad({ kind: 'open', view: outcome.view });
      else setLoad({ kind: outcome.kind === 'signed-out' ? 'signed-out' : 'failed' });
    });
    return () => {
      alive = false;
    };
  }, [registrationId]);

  if (load.kind === 'loading') return <p className={styles.text}>Loading your registration.</p>;
  if (load.kind === 'signed-out') return <p className={styles.notice} role="status">{SIGNED_OUT}</p>;
  if (load.kind === 'failed') return <p className={styles.notice} role="status">{LOAD_FAILED}</p>;

  const { view } = load;
  const details = view.details ?? {};
  switch (view.status) {
    case 'submitted':
    case 'in-review':
      return <InReview submittedAt={view.submittedAt} />;
    case 'needs-changes':
      return (
        <NeedsChanges
          notes={view.notes ?? []}
          noteFrom={view.noteFrom}
          registrationId={registrationId}
          spoaPhone={details.spoaPhone}
        />
      );
    case 'approved':
      return <Approved registrationId={registrationId} />;
    case 'live':
      return <Live serviceName={view.serviceName} firstPromptAt={view.firstPromptAt} />;
    case 'not-approved':
      return <NotApproved registrationId={registrationId} reason={view.reason} />;
    case 'reverify':
      return <Reverify registrationId={registrationId} serviceName={view.serviceName} details={details} />;
    default:
      return <p className={styles.notice} role="status">{LOAD_FAILED}</p>;
  }
}
