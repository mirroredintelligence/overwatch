import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { StatusBadge } from '@/components/ui/StatusBadge';
import { agoText, clockTime } from '@/lib/lead/format';
import type { GettingOldItem } from '@/lib/lead/types';
import styles from './Lead.module.css';

// A service whose figure is still on schedule but getting old (W17). The status is a badge with its word.

export type OldFigureCardProps = {
  item: GettingOldItem;
  /** The clock, epoch ms, for "ago". */
  now: number;
  onAsk: () => void;
};

export function OldFigureCard({ item, now, onAsk }: OldFigureCardProps) {
  return (
    <Card heading={item.name} headingLevel={3} dataEl="LEAD-OLD-CARD">
      <p className={styles.line}>
        {`Reported ${agoText(item.reportedAt, now)}. Next due ${clockTime(item.nextDueAt)}. On schedule, but the figure is getting old.`}
      </p>
      <StatusBadge status={item.status} />
      <div className={styles.actions}>
        <Button variant="secondary" dataEl="LEAD-OLD-ASK-BTN" onClick={onAsk}>
          Ask for an update now
        </Button>
      </div>
    </Card>
  );
}
