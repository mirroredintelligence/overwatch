'use client';

import { type ReactNode, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { CANNOT_DO, leadPost } from '@/lib/lead/browser';
import { clockTime } from '@/lib/lead/format';
import { invitedAs } from '@/lib/lead/invitations';
import { SETUP_STEPS, STEP_LABEL, stuckAt } from '@/lib/lead/setupProgress';
import { LeadPhonedDialog } from './LeadPhonedDialog';
import { reporterStatus } from './ReporterList';
import type { Invitation } from './SetupTracker';
import styles from './ReporterDetail.module.css';

// One reporter's set-up (INV-01): the seven steps as a timeline, what the lead can do about it, and a row to
// change their number. The data has a time for "Invited" and the last-seen time only, so no other step has a
// time, and the chosen channel and the masked number are not shown. On a phone the detail is a full-screen step
// with a Back button, and the actions stick to the bottom.

export type ReporterDetailProps = {
  item: Invitation;
  /** Epoch ms, the page's one moment, so the status here is the one the list shows. */
  now: number;
  onBack: () => void;
  onNotice: (text: string, failed: boolean) => void;
  /** The change-number form (INV-03). Without it the row is a link to the change-number page. */
  changeNumber?: ReactNode;
};

export function ReporterDetail({ item, now, onBack, onNotice, changeNumber }: ReporterDetailProps) {
  const status = reporterStatus(item, now);
  const waiting = stuckAt(item.steps);
  const [phoned, setPhoned] = useState(false);
  const [busy, setBusy] = useState(false);
  const base = `/api/bff/lead/invitations/${encodeURIComponent(item.id)}`;
  const seen = `Invited ${clockTime(item.invitedAt)}, last seen ${clockTime(item.lastSeen)}.`;

  async function act(path: string, done: string, failed: string) {
    setBusy(true);
    const result = await leadPost(path);
    setBusy(false);
    if (result.ok) onNotice(done, false);
    else onNotice(result.status === 403 ? CANNOT_DO : failed, true);
  }

  return (
    <section className={styles.detail} aria-label={`${item.serviceName} set-up`} data-complete={waiting === null}>
      <div className={styles.main}>
        <button type="button" className={styles.back} onClick={onBack}>
          <svg viewBox="0 0 20 20" width="20" height="20" aria-hidden="true" focusable="false">
            <path d="M12 5l-5 5 5 5" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Back to the list
        </button>
        <div>
          <h2 className={styles.name}>{item.serviceName}</h2>
          <p className={styles.sub}>{`${invitedAs(item)} · invited ${clockTime(item.invitedAt)}`}</p>
        </div>

        {waiting === null ? (
          <p className={styles.callout} data-tone="done">
            {item.firstReportAt !== null ? `Complete. First report ${clockTime(item.firstReportAt)}.` : 'Complete.'}
          </p>
        ) : (
          <p className={styles.callout} data-tone={status === 'stuck' ? 'stuck' : 'progress'}>
            <strong>{status === 'stuck' ? `Stuck at: ${waiting}.` : 'In progress.'}</strong> {seen}
          </p>
        )}

        <ol aria-label="Set-up steps" className={styles.timeline}>
          {SETUP_STEPS.map((step) => {
            const state = item.steps[step] ? 'done' : STEP_LABEL[step] === waiting ? 'waiting' : 'todo';
            return (
              <li key={step} className={styles.step} data-state={state}>
                <span className={styles.dot} aria-hidden="true" />
                <span className={styles.label}>
                  <strong>{STEP_LABEL[step]}</strong>
                  {step === 'invited' ? <span className={styles.time}>{` ${clockTime(item.invitedAt)}`}</span> : null}
                  {state === 'waiting' ? (
                    <>
                      <span className={styles.srOnly}>. </span>
                      <span className={styles.here}>Waiting here</span>
                      <span className={styles.srOnly}>.</span>
                    </>
                  ) : (
                    <span className={styles.srOnly}>{state === 'done' ? '. Done.' : '. Not done.'}</span>
                  )}
                </span>
              </li>
            );
          })}
        </ol>
      </div>

      {waiting !== null ? (
        <div className={styles.actions} role="group" aria-label="What you can do">
          <div className={styles.eyebrow}>What you can do</div>
          <div className={styles.buttons}>
            <Button
              variant="primary"
              busy={busy}
              onClick={() => void act(`${base}/resend`, 'Invitation sent again.', 'The invitation could not be sent again.')}
              dataEl="LEAD-TRACK-RESEND-BTN"
            >
              Resend the invitation
            </Button>
            <Button
              variant="secondary"
              busy={busy}
              onClick={() => void act(`${base}/switch-to-text`, 'They are switched to text.', 'They could not be switched to text.')}
              dataEl="LEAD-TRACK-TEXT-BTN"
            >
              Switch them to text
            </Button>
            <Button variant="secondary" onClick={() => setPhoned(true)} dataEl="LEAD-TRACK-PHONE-BTN">
              Phone them
            </Button>
          </div>
          <div className={styles.number}>
            {changeNumber ?? (
              <a className={styles.numberLink} href={`/lead/reporters/number?service=${encodeURIComponent(item.serviceId)}`}>
                Change their number
              </a>
            )}
            <p className={styles.hint}>The new number gets a fresh code. The old one stops working.</p>
          </div>
        </div>
      ) : null}
      <LeadPhonedDialog open={phoned} serviceId={item.serviceId} serviceName={item.serviceName} onClose={() => setPhoned(false)} />
    </section>
  );
}
