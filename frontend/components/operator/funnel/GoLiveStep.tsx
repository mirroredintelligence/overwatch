'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { whenText } from '@/lib/tenantAdmin/words';
import type { Funnel, FunnelStep, PhaseId } from '@/lib/operator/funnel';
import styles from '@/components/admin/admin.module.css';
import ts from '../Tenant.module.css';
import { useStep, type LifecycleProps } from './shared';

// The last step of the Go live page (TEN-083). Going live is asked for in a dialog that says what it does, and sent
// once with one idempotency key per submit.

export function GoLiveStep(props: LifecycleProps & { funnel: Funnel; step: FunnelStep; onSelectPhase: (phase: PhaseId) => void }) {
  const [asking, setAsking] = useState(false);
  const { run, busy } = useStep(props);
  const { funnel, step } = props;
  const status = props.detail.tenant.status;
  async function goLive() {
    setAsking(false);
    await run('POST', 'activation', undefined, () => 'The organisation is live.', () => 'It cannot go live yet. The page has been read again.');
  }
  const state = step.done ? 'done' : 'todo';
  const left = funnel.leftByPhase;
  return (
    <div id="step-golive" className={ts.step} data-el="OP-STEP-GOLIVE" data-state={state}>
      {status !== 'provisioning' ? (
        <p className={styles.ok}>{`This organisation is live${props.detail.tenant.activatedAt !== null ? ` since ${whenText(props.detail.tenant.activatedAt)}` : ''}.`}</p>
      ) : funnel.canGoLive ? (
        <div className={ts.ready}>
          <p className={ts.text}>Everything is ready. Once it is live, their people can sign in.</p>
          <div className={styles.actions}>
            <Button variant="primary" busy={busy} onClick={() => setAsking(true)} dataEl="OP-ACTIVATE-BTN">
              Go live
            </Button>
          </div>
        </div>
      ) : (
        <>
          {left.length > 0 ? (
            <>
              <h3 className={ts.blockTitle}>What is left for you</h3>
              <ul className={ts.leftList} aria-label="Still to do">
                {left.map((item) => (
                  <li key={item.phase}>
                    <a
                      className={ts.leftLink}
                      href={`#phase-${item.phase}`}
                      onClick={(event) => {
                        event.preventDefault();
                        props.onSelectPhase(item.phase);
                      }}
                    >
                      {item.title}
                    </a>{' '}
                    <span>{item.waiting ? 'waiting for their administrator' : `${item.count} ${item.count === 1 ? 'thing' : 'things'} left`}</span>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className={styles.ok}>Everything you have to do is done.</p>
          )}
          {funnel.byThem.length > 0 ? (
            <div className={ts.theirs}>
              <h3 className={ts.blockTitle}>Their administrators finish these after they sign in</h3>
              <ul className={ts.theirList} aria-label="Their administrators finish these">
                {funnel.byThem.map((words) => (
                  <li key={words}>{words}</li>
                ))}
              </ul>
              <p className={styles.muted}>Overwatch will make Go live available when these are done.</p>
            </div>
          ) : left.length === 0 ? (
            <p className={styles.muted}>Overwatch will make Go live available when it has checked everything.</p>
          ) : null}
        </>
      )}
      {asking ? (
        <Dialog title="Go live with this organisation?" sub="Its people will be able to sign in." onClose={() => setAsking(false)}>
          <div className={styles.actions}>
            <Button variant="primary" onClick={() => void goLive()}>
              Yes, go live
            </Button>
            <Button variant="neutral" onClick={() => setAsking(false)}>
              Cancel
            </Button>
          </div>
        </Dialog>
      ) : null}
    </div>
  );
}
