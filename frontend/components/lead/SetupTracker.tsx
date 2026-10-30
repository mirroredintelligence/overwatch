'use client';

import { useEffect, useState } from 'react';
import { LeadPhonedDialog } from './LeadPhonedDialog';
import { Button } from '@/components/ui/Button';
import { ShapeIcon } from '@/components/ui/StatusBadge';
import { CANNOT_DO, leadPost, leadRead } from '@/lib/lead/browser';
import { listOf, textOf } from '@/lib/lead/answers';
import { clockTime } from '@/lib/lead/format';
import { SETUP_STEPS, STEP_LABEL, stuckAt, type SetupSteps } from '@/lib/lead/setupProgress';
import styles from './Lead.module.css';

// Set-up progress for each invitation (W43): the seven steps in words and with icons, where the set-up is
// stuck, and what the lead can do about it. A set-up that is complete says so, with its first report time.

export type Invitation = {
  id: string;
  serviceName: string;
  role: string;
  steps: SetupSteps;
  invitedAt: string;
  lastSeen: string;
  firstReportAt: string | null;
};

function invitationsFrom(body: unknown): Invitation[] {
  return listOf(body, 'items').map((item) => {
    const row = item as Record<string, unknown>;
    const steps = row.steps as Record<string, unknown>;
    const flags = {} as SetupSteps;
    for (const step of SETUP_STEPS) {
      if (typeof steps?.[step] !== 'boolean') throw new Error('step');
      flags[step] = steps[step] as boolean;
    }
    return {
      id: textOf(row.id),
      serviceName: textOf(row.serviceName),
      role: textOf(row.role),
      steps: flags,
      invitedAt: textOf(row.invitedAt),
      lastSeen: textOf(row.lastSeen),
      firstReportAt: typeof row.firstReportAt === 'string' ? row.firstReportAt : null,
    };
  });
}

function TrackedInvitation({ item, onNotice }: { item: Invitation; onNotice: (text: string, failed: boolean) => void }) {
  const stuck = stuckAt(item.steps);
  const [phoned, setPhoned] = useState(false);
  const [text, setText] = useState<string | null>(null);

  async function act(path: string, done: string, failed: string) {
    const result = await leadPost(path);
    if (result.ok) {
      setText(done);
      onNotice(done, false);
    } else {
      const message = result.status === 403 ? CANNOT_DO : failed;
      setText(message);
      onNotice(message, true);
    }
  }

  return (
    <section className={styles.card} aria-labelledby={`track-${item.id}`}>
      <h2 id={`track-${item.id}`} className={styles.sectionHeading}>
        {item.serviceName}
      </h2>
      <p className={styles.muted}>{item.role}</p>
      <ol aria-label="Set-up steps" className={styles.steps}>
        {SETUP_STEPS.map((step) => (
          <li key={step}>
            <span className={styles.done}>
              <ShapeIcon shape={item.steps[step] ? 'circle-tick' : 'dashed-circle'} />
              {`${STEP_LABEL[step]}. ${item.steps[step] ? 'Done.' : 'Not done.'}`}
            </span>
          </li>
        ))}
      </ol>
      {stuck !== null ? (
        <>
          <p className={styles.line}>
            {`Stuck at: ${stuck}. Invited ${clockTime(item.invitedAt)}, last seen ${clockTime(item.lastSeen)}.`}
          </p>
          <div className={styles.actions}>
            <Button
              variant="primary"
              onClick={() => void act(`/api/bff/lead/invitations/${encodeURIComponent(item.id)}/resend`, 'Invitation sent again.', 'The invitation could not be sent again.')}
              dataEl="LEAD-TRACK-RESEND-BTN"
            >
              Resend invitation
            </Button>
            <Button
              variant="secondary"
              onClick={() => void act(`/api/bff/lead/invitations/${encodeURIComponent(item.id)}/switch-to-text`, 'They are switched to text.', 'They could not be switched to text.')}
              dataEl="LEAD-TRACK-TEXT-BTN"
            >
              Switch them to text
            </Button>
            <Button variant="neutral" onClick={() => setPhoned(true)} dataEl="LEAD-TRACK-PHONE-BTN">
              Phone them
            </Button>
          </div>
        </>
      ) : (
        <p className={styles.line}>
          {item.firstReportAt !== null ? `Complete. First report ${clockTime(item.firstReportAt)}.` : 'Complete.'}
        </p>
      )}
      {text !== null ? <p className={styles.muted}>{text}</p> : null}
      <LeadPhonedDialog open={phoned} serviceId={item.serviceId} serviceName={item.serviceName} onClose={() => setPhoned(false)} />
    </section>
  );
}

export function SetupTracker() {
  const [items, setItems] = useState<Invitation[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [notice, setNotice] = useState<{ text: string; failed: boolean } | null>(null);

  useEffect(() => {
    let cancelled = false;
    void leadRead('/api/bff/lead/invitations').then((result) => {
      if (cancelled) return;
      try {
        if (!result.ok) throw new Error('refused');
        setItems(invitationsFrom(result.body));
      } catch {
        setFailed(true);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>Set-up progress</h1>
      {failed ? (
        <p role="alert" className={styles.fieldError}>
          We could not load the set-up progress.
        </p>
      ) : null}
      {!failed && items === null ? <p className={styles.muted}>Loading the set-up progress.</p> : null}
      <div className={styles.stack}>
        {items?.map((item) => (
          <TrackedInvitation
            key={item.id}
            item={item}
            onNotice={(text, isFailed) => setNotice({ text, failed: isFailed })}
          />
        ))}
      </div>
      <p role={notice?.failed ? 'alert' : 'status'} className={notice?.failed ? styles.fieldError : styles.line}>
        {notice?.text ?? ''}
      </p>
    </main>
  );
}
