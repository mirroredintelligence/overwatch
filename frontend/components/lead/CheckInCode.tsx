'use client';

import { useId, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { leadPost } from '@/lib/lead/browser';
import { type CheckinCode, matrixPath, parseCheckinCode } from '@/lib/lead/checkin';
import styles from './CheckInCode.module.css';

// The code a service prints and pins up (DEC-1346). A duty manager scans it, is texted a six-digit code on their
// registered number, and goes on or off shift from the page it opens. Making a new code stops the printed one, so the
// page says so before it is pressed. The code is drawn here from the matrix the back end made.

const QUIET_ZONE = 4;

type State = { kind: 'idle' } | { kind: 'made'; code: CheckinCode } | { kind: 'failed' };

export function CheckInCode({ serviceId }: { serviceId: string }) {
  const [state, setState] = useState<State>({ kind: 'idle' });
  const [busy, setBusy] = useState(false);
  const titleId = useId();

  async function make() {
    setBusy(true);
    const result = await leadPost(`/api/bff/lead/services/${encodeURIComponent(serviceId)}/checkin-code`, {});
    setBusy(false);
    if (!result.ok) {
      setState({ kind: 'failed' });
      return;
    }
    try {
      setState({ kind: 'made', code: parseCheckinCode(result.body) });
    } catch {
      setState({ kind: 'failed' });
    }
  }

  return (
    <section className={styles.card} aria-labelledby={titleId} data-el="LEAD-CHECKIN">
      <h2 id={titleId} className={styles.heading} data-noprint>
        Check-in code to print
      </h2>
      <p className={styles.note} data-noprint>
        Pin this up where the duty manager works. They scan it, get a code by text on their registered number, and go on or off shift. Making a new
        code stops the one already printed.
      </p>
      {state.kind === 'made' ? (
        <div className={styles.print} data-print>
          <p className={styles.service}>{state.code.service}</p>
          <svg
            role="img"
            aria-label={`QR code to check in to ${state.code.service}`}
            className={styles.qr}
            viewBox={`${-QUIET_ZONE} ${-QUIET_ZONE} ${state.code.size + 2 * QUIET_ZONE} ${state.code.size + 2 * QUIET_ZONE}`}
            shapeRendering="crispEdges"
          >
            <rect x={-QUIET_ZONE} y={-QUIET_ZONE} width={state.code.size + 2 * QUIET_ZONE} height={state.code.size + 2 * QUIET_ZONE} fill="#fff" />
            <path d={matrixPath(state.code.rows)} fill="#000" />
          </svg>
          <p className={styles.help}>Scan to go on or off shift.</p>
          <p className={styles.address}>{state.code.url}</p>
        </div>
      ) : null}
      {state.kind === 'failed' ? (
        <p role="alert" className={styles.failed} data-noprint>
          The code could not be made. Try again.
        </p>
      ) : null}
      <div className={styles.actions} data-noprint>
        <Button variant={state.kind === 'made' ? 'secondary' : 'primary'} busy={busy} onClick={() => void make()} dataEl="LEAD-CHECKIN-MAKE-BTN">
          {state.kind === 'made' ? 'Make a new code' : 'Make a check-in code'}
        </Button>
        {state.kind === 'made' ? (
          <Button variant="primary" onClick={() => window.print()} dataEl="LEAD-CHECKIN-PRINT-BTN">
            Print
          </Button>
        ) : null}
      </div>
    </section>
  );
}
