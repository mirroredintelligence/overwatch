import Link from 'next/link';
import { Button } from '@/components/ui/Button';
import { StatusBadge, STATUS_LABELS, type StatusCode } from '@/components/ui/StatusBadge';
import type { Board, BoardEntry } from '@/lib/board/types';
import { attentionLine, limitedOrWorse, needsAttention, pressureChip } from '@/lib/exec/homeSummary';
import styles from './Exec.module.css';

// The executive's home (W40, ExecApp1 screen 1). Server-rendered: it holds no patient information and
// no state. The name is the organisation's (or the network's) from the board, never a constant.

const COUNTED: readonly StatusCode[] = ['accepting', 'limited', 'not-accepting', 'over-capacity', 'not-updated'];

function countsByStatus(board: Board): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const entry of board.entries) counts[entry.status] = (counts[entry.status] ?? 0) + 1;
  return counts;
}

export function ExecHome({ board, name }: { board: Board; name: string }) {
  const chip = pressureChip(board.pressure);
  const { limited, inHours } = limitedOrWorse(board);
  const attention: BoardEntry[] = needsAttention(board);
  const counts = countsByStatus(board);

  return (
    <div className={styles.stack}>
      <header className={styles.stack}>
        <h1 className={styles.heading}>{name}</h1>
        <p data-el="EXEC-HOME-PRESSURE" aria-label={chip.label} className={styles.pressure}>
          <span className={styles.chipWord}>{chip.word}</span>
          <span>{`${limited} of ${inHours} services limited or worse`}</span>
        </p>
      </header>

      <section className={styles.section} aria-label="Counts by status">
        <ul className={styles.counts}>
          {COUNTED.map((status) => (
            <li key={status}>
              <StatusBadge status={status} />
              <span className={styles.count}>{counts[status] ?? 0}</span>
              <span className={styles.srOnly}>{STATUS_LABELS[status]}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className={styles.section} aria-labelledby="exec-attention-heading">
        <h2 id="exec-attention-heading" className={styles.heading}>{`Needs attention (${attention.length})`}</h2>
        <ul className={styles.attention} aria-label={`Needs attention (${attention.length})`}>
          {attention.map((entry) => (
            <li key={entry.serviceId}>
              <Link href={`/planning/services/${encodeURIComponent(entry.serviceId)}`} className={styles.serviceLink}>
                <span className={styles.serviceName}>{entry.name}</span>
                <span className={styles.attentionLine}>{attentionLine(entry, board.generatedAt)}</span>
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <div className={styles.actions}>
        <Button variant="secondary" href="/planning/services" dataEl="EXEC-HOME-SEEALL-BTN">
          See all services
        </Button>
        <Button variant="secondary" href="/planning/flows" dataEl="EXEC-HOME-FLOWS-BTN">
          See planning flows
        </Button>
      </div>
    </div>
  );
}
