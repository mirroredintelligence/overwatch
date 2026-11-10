'use client';

import { useState, type ReactElement } from 'react';
import { askService } from '@/lib/advisor/v2/browser';
import styles from './ServiceCheck.module.css';

// The two actions on the service page (DEC-1377). "Book a slot" opens the patient check in the thread (it does not book).
// "Request a capacity update" texts the service's duty manager, so it asks first and says what happened: it is never a
// silent press. One open request at a time: the back end's 409 is shown as "already asked".

type Ask = 'idle' | 'confirming' | 'sending' | 'queued' | 'already' | 'failed';

const SAID: Record<'queued' | 'already' | 'failed', string> = {
  queued: 'The service has been asked for its figure. It is texted now.',
  already: 'The service cannot be asked right now. A request may already be waiting, so wait for its reply or phone the service.',
  failed: 'The request could not be sent. Phone the service.',
};

export function ServiceActions({ serviceId, onCheck }: { serviceId: string; onCheck: () => void }): ReactElement {
  const [ask, setAsk] = useState<Ask>('idle');

  async function send() {
    setAsk('sending');
    const result = await askService(serviceId);
    setAsk(result.kind);
  }

  return (
    <div className={styles.actions}>
      <button type="button" className={`${styles.button} ${styles.primary}`} onClick={onCheck}>
        Book a slot
      </button>
      {ask === 'confirming' ? (
        <>
          <button type="button" className={styles.button} onClick={() => void send()}>
            Yes, text the service now
          </button>
          <button type="button" className={styles.button} onClick={() => setAsk('idle')}>
            Cancel
          </button>
        </>
      ) : (
        <button type="button" className={styles.button} disabled={ask === 'sending'} onClick={() => setAsk('confirming')}>
          Request capacity update
        </button>
      )}
      {ask === 'queued' || ask === 'already' || ask === 'failed' ? (
        <p role="status" className={styles.status}>
          {SAID[ask]}
        </p>
      ) : null}
    </div>
  );
}
