import { useId } from 'react';
import { ShapeIcon } from '@/components/ui/StatusBadge';
import { Button } from '@/components/ui/Button';
import { clockTime, overdueText } from '@/lib/lead/format';
import type { ChaseItem, LadderRow, LadderStep } from '@/lib/lead/types';
import styles from './ChaseCard.module.css';

// One service the shift lead must chase (W17): when its report was due, how late it is, and the
// missed-report ladder, with each step's state in words and an icon (never colour alone).

export type ChaseCardProps = {
  item: ChaseItem;
  onEnterPhoned: () => void;
  onRemind: () => void;
  /** Set on the open card (the board's state 2): it gets a Close button and the suspend link. */
  onClose?: () => void;
};

const LABEL: Record<LadderStep, string> = {
  prompt: 'Text sent',
  reminder: 'Reminder sent',
  'phone-task': 'Advisor phone task',
  escalate: 'Escalated to you',
};

// The phone's one line: "Text 12:00 done · Reminder 12:30 done · Phone task not done · Escalated to you".
function oneLineStep(row: LadderRow): string {
  const state = row.done ? 'done' : 'not done';
  switch (row.step) {
    case 'prompt':
      return `Text ${clockTime(row.at)} ${state}`;
    case 'reminder':
      return `Reminder ${clockTime(row.at)} ${state}`;
    case 'phone-task':
      return `Phone task ${state}`;
    case 'escalate':
      return 'Escalated to you';
  }
}

// The ladder as four ordered steps. Each step's state is words; the shape is decoration. At phone width
// the steps are replaced by the one line of text.
export function LadderTimeline({ ladder }: { ladder: readonly LadderRow[] }) {
  return (
    <>
      <ol className={styles.timeline} data-el="LEAD-CHASE-LADDER">
        {ladder.map((row) => (
          <li key={row.step} className={styles.step} data-state={row.done ? 'done' : 'not-done'}>
            <span className={styles.marker} data-step={row.step} aria-hidden="true">
              <ShapeIcon shape={row.done ? 'circle-tick' : 'dashed-circle'} />
            </span>
            <div>
              <p className={styles.stepTitle}>
                <time dateTime={row.at}>{clockTime(row.at)}</time>
                {` · ${LABEL[row.step]}`}
              </p>{' '}
              <p className={styles.stepState}>{row.done ? 'Done.' : 'Not done.'}</p>
            </div>
          </li>
        ))}
      </ol>
      <p className={styles.oneLine} data-el="LEAD-CHASE-LADDER-LINE">
        {ladder.map(oneLineStep).join(' · ')}
      </p>
    </>
  );
}

export function ChaseCard({ item, onEnterPhoned, onRemind, onClose }: ChaseCardProps) {
  const headingId = useId();
  const open = onClose !== undefined;
  return (
    <section
      aria-labelledby={headingId}
      data-el="LEAD-CHASE-CARD"
      className={open ? `${styles.card} ${styles.open}` : styles.card}
    >
      <div className={styles.head}>
        <div className={styles.titleBlock}>
          {open ? <p className={styles.kicker}>Chasing</p> : null}
          <h3 id={headingId} className={styles.title}>
            {item.name}
          </h3>
          <p className={styles.line}>
            {`Report was due ${clockTime(item.dueAt)}. Overdue by ${overdueText(item.overdueMinutes)}. Last figure: ${item.lastValueText}.`}
          </p>
        </div>
        {onClose ? (
          <Button variant="neutral" onClick={onClose} dataEl="LEAD-CHASE-CLOSE-BTN">
            Close
          </Button>
        ) : null}
      </div>
      <p className={styles.unknown}>Shown as unknown on the board</p>
      <LadderTimeline ladder={item.ladder} />
      <div className={styles.actions}>
        <Button variant="primary" dataEl="LEAD-CHASE-PHONED-BTN" onClick={onEnterPhoned}>
          Enter what they told me by phone
        </Button>
        <Button variant="secondary" dataEl="LEAD-CHASE-REMIND-BTN" onClick={onRemind}>
          Send reminder again
        </Button>
        <Button
          variant="neutral"
          href={`/lead/reporters/number?service=${encodeURIComponent(item.serviceId)}`}
          dataEl="LEAD-CHASE-NUMBER-LINK"
        >
          Change number
        </Button>
        {open ? (
          <Button
            variant="neutral"
            href={`/lead/services/${encodeURIComponent(item.serviceId)}/suspend`}
            dataEl="LEAD-CHASE-SUSPEND-LINK"
          >
            Suspend this service
          </Button>
        ) : null}
      </div>
    </section>
  );
}
