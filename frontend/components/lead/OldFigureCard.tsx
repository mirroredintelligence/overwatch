import { useId } from 'react';
import { Button } from '@/components/ui/Button';
import { StatusBadge } from '@/components/ui/StatusBadge';
import { agoText, clockTime } from '@/lib/lead/format';
import type { GettingOldItem } from '@/lib/lead/types';
import styles from './OldFigureCard.module.css';

// A service whose figure is still on schedule but getting old (W17). One row: the service and when it reported,
// the status as shape plus word, and the one action. `disabled` switches the action off while the page is
// showing figures it could not refresh.

export type OldFigureCardProps = {
  item: GettingOldItem;
  /** The clock, epoch ms, for "ago". */
  now: number;
  onAsk: () => void;
  disabled?: boolean;
  /** What the last ask did for this service, said here so the press is never silent. */
  feedback?: { text: string; failed: boolean } | null;
};

export function OldFigureCard({ item, now, onAsk, disabled = false, feedback = null }: OldFigureCardProps) {
  const headingId = useId();
  return (
    <section className={styles.card} aria-labelledby={headingId} data-el="LEAD-OLD-CARD">
      <div className={styles.text}>
        <h3 id={headingId} className={styles.title}>
          {item.name}
        </h3>
        <p className={styles.line}>
          {`Reported ${agoText(item.reportedAt, now)} · next due ${clockTime(item.nextDueAt)} · on schedule, but the figure is getting old`}
        </p>
      </div>
      <StatusBadge status={item.status} />
      <Button variant="secondary" dataEl="LEAD-OLD-ASK-BTN" disabled={disabled} onClick={onAsk}>
        Ask for an update now
      </Button>
      {feedback !== null ? (
        <p role="status" className={styles.feedback} data-failed={feedback.failed || undefined}>
          {feedback.text}
        </p>
      ) : null}
    </section>
  );
}
