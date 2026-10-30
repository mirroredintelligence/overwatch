import { ShapeIcon } from '@/components/ui/StatusBadge';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { clockTime, overdueText } from '@/lib/lead/format';
import type { ChaseItem, LadderRow, LadderStep } from '@/lib/lead/types';
import styles from './Lead.module.css';

// One service the shift lead must chase (W17): when its report was due, how late it is, and the
// missed-report ladder, with each step's state in words and an icon (never colour alone).

export type ChaseCardProps = {
  item: ChaseItem;
  onEnterPhoned: () => void;
  onRemind: () => void;
};

const LABEL: Record<LadderStep, string> = {
  prompt: 'Text sent',
  reminder: 'Reminder sent',
  'phone-task': 'Advisor phone task',
  escalate: 'Escalated to you',
};

function LadderItem({ row }: { row: LadderRow }) {
  return (
    <li>
      <time dateTime={row.at}>{clockTime(row.at)}</time>{' '}
      <span>{`${LABEL[row.step]}.`}</span>{' '}
      <span className={styles.done}>
        <ShapeIcon shape={row.done ? 'circle-tick' : 'dashed-circle'} />
        {row.done ? 'Done.' : 'Not done.'}
      </span>
    </li>
  );
}

export function ChaseCard({ item, onEnterPhoned, onRemind }: ChaseCardProps) {
  return (
    <Card heading={item.name} headingLevel={3} dataEl="LEAD-CHASE-CARD">
      <p className={styles.line}>
        {`Report was due ${clockTime(item.dueAt)}. Overdue by ${overdueText(item.overdueMinutes)}. Last figure: ${item.lastValueText}.`}
      </p>
      <p className={styles.muted}>Shown as unknown on the board</p>
      <ol className={styles.ladder} data-el="LEAD-CHASE-LADDER">
        {item.ladder.map((row) => (
          <LadderItem key={row.step} row={row} />
        ))}
      </ol>
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
      </div>
    </Card>
  );
}
