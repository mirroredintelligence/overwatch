'use client';

import { type KeyboardEvent, type ReactNode, useEffect, useId, useRef, useState } from 'react';
import { leadPost, newIdempotencyKey } from '@/lib/lead/browser';
import type { ScreenRow } from '@/lib/screens/admin';
import styles from './ScreenList.module.css';

// Unpair a wall screen (docs/design/redesign/boards/lead/Screens.dc.html, "Unpair this screen?"; W9I,
// TEN-072). It asks first, in place of the screen's own card, names the screen and says what happens, and
// ends it at once at the back end: the screen then goes back to its pairing code. The safe choice (Keep it)
// has the focus when the question opens, and Escape keeps the screen too. The key and the busy flag live
// here, so a new question for another screen starts with a new key and a second try of the same one sends
// the same key (the back end then answers it as one revoke).

export type UnpairOutcome = 'done' | 'gone' | 'ended';

export function ScreenUnpair({
  row,
  status,
  onClose,
  onResult,
}: {
  row: ScreenRow;
  /** The screen's status tag, as the card shows it. */
  status: ReactNode;
  onClose: () => void;
  onResult: (result: UnpairOutcome) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const key = useRef<string>(newIdempotencyKey());
  const sending = useRef(false);
  const keep = useRef<HTMLButtonElement>(null);
  const titleId = useId();

  useEffect(() => {
    keep.current?.focus();
  }, []);

  async function unpair() {
    if (sending.current) return;
    sending.current = true;
    setBusy(true);
    setFailed(false);
    const result = await leadPost(`/api/bff/screens/${encodeURIComponent(row.deviceId)}/revoke`, undefined, key.current);
    sending.current = false;
    setBusy(false);
    if (result.ok) onResult('done');
    else if (result.status === 404) onResult('gone');
    else if (result.status === 401 || result.status === 403) onResult('ended');
    else setFailed(true);
  }

  function onKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key !== 'Escape') return;
    event.stopPropagation();
    onClose();
  }

  return (
    <section className={styles.confirm} aria-labelledby={titleId} data-el="SCREENS-UNPAIR-CONFIRM" onKeyDown={onKeyDown}>
      <h2 id={titleId} className={styles.kicker}>
        Unpair this screen?
      </h2>
      <div className={styles.confirmHead}>
        <p className={styles.confirmName}>{row.name}</p>
        {status}
      </div>
      <p className={styles.confirmText}>It stops showing the board at once and goes back to asking for a code. You can pair it again later.</p>
      {failed ? (
        <p role="alert" className={styles.confirmError}>
          The screen could not be unpaired. Try again.
        </p>
      ) : null}
      <div className={styles.confirmActions}>
        <button
          type="button"
          className={styles.dangerButton}
          disabled={busy}
          aria-busy={busy ? 'true' : undefined}
          onClick={() => void unpair()}
          data-el="SCREENS-UNPAIR-CONFIRM-BTN"
        >
          {`Unpair ${row.name}`}
        </button>
        <button ref={keep} type="button" className={styles.keepButton} onClick={onClose} data-el="SCREENS-CLAIM-CANCEL-BTN">
          Keep it
        </button>
      </div>
    </section>
  );
}
