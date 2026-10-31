'use client';

import { useRef, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { leadPost, newIdempotencyKey } from '@/lib/lead/browser';
import type { ScreenRow } from '@/lib/screens/admin';
import dialogStyles from '@/components/advisor/dialog-body.module.css';

// Unpair a wall screen (docs/design/network-ui.md section 6, ScreenUnpair; W9I, TEN-072). It asks first,
// names the screen, and ends it at once at the back end: the screen then goes back to its pairing code.
// The key and the busy flag live here, so a new dialog for another screen starts with a new key and a
// second try of the same one sends the same key (the back end then answers it as one revoke).

export type UnpairOutcome = 'done' | 'gone' | 'ended';

export function ScreenUnpair({ row, onClose, onResult }: { row: ScreenRow; onClose: () => void; onResult: (result: UnpairOutcome) => void }) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const key = useRef<string>(newIdempotencyKey());
  const sending = useRef(false);

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

  return (
    <Dialog title={`Unpair ${row.name}?`} dataEl="SCREENS-UNPAIR-DIALOG" onClose={onClose}>
      <p className={dialogStyles.text}>The screen stops showing the board and returns to its pairing code. You can pair it again at any time.</p>
      {failed ? (
        <p role="alert" className={dialogStyles.error}>
          The screen could not be unpaired. Try again.
        </p>
      ) : null}
      <div className={dialogStyles.actions}>
        <Button variant="neutral" onClick={onClose} dataEl="SCREENS-CLAIM-CANCEL-BTN">
          Cancel
        </Button>
        <Button variant="primary" busy={busy} onClick={() => void unpair()} dataEl="SCREENS-UNPAIR-CONFIRM-BTN">
          Unpair screen
        </Button>
      </div>
    </Dialog>
  );
}
