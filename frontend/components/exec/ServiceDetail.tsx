import Link from 'next/link';
import { StatusBadge, type StatusCode } from '@/components/ui/StatusBadge';
import type { BoardEntry } from '@/lib/board/types';
import { dataAgeText } from '@/lib/board/format';
import { telHref } from '@/lib/exec/call';
import styles from './Exec.module.css';

// One service for the executive (W40, ExecApp2 screen 4). The figure is the board's own: over established
// capacity by a count, or what is free. "Call the duty coordinator" is shown only when the board holds the
// tenant's number (DEC-777): no number is made up.

type Figure = { big: string; small: string };

function figureOf(entry: BoardEntry): Figure | null {
  if (entry.overBy !== null && entry.overBy > 0) return { big: `+${entry.overBy}`, small: 'over established capacity' };
  if (entry.effectiveAvailable !== null) return { big: String(entry.effectiveAvailable), small: `${entry.unitLabel} free` };
  return null;
}

export function ServiceDetail({ entry, now, coordinationPhone = null }: { entry: BoardEntry; now: string; coordinationPhone?: string | null }) {
  const figure = figureOf(entry);
  return (
    <div className={styles.stack}>
      <h1 className={styles.heading}>{entry.name}</h1>
      <p>
        <StatusBadge status={entry.status as StatusCode} size="lg" />
      </p>
      <p className={styles.footer}>
        {entry.reportedAt === null ? 'No report yet' : `Updated ${dataAgeText(entry.reportedAt, now)}`}
      </p>
      {figure ? (
        <section className={styles.section} aria-label="Figure">
          <p className={styles.big}>{figure.big}</p>
          <p>{figure.small}</p>
          {entry.used !== null ? <p>{`${entry.used} of ${entry.established} ${entry.unitLabel}`}</p> : null}
        </section>
      ) : null}
      {coordinationPhone !== null ? (
        <p>
          <a href={telHref(coordinationPhone)} className={styles.backLink} data-el="EXEC-SERVICE-CALL-LINK">Call the duty coordinator</a>
          {' '}
          <span>{coordinationPhone}</span>
        </p>
      ) : null}
      <div className={styles.actions}>
        <Link href="/planning/alerts" className={styles.backLink}>Back to alerts</Link>
      </div>
    </div>
  );
}
