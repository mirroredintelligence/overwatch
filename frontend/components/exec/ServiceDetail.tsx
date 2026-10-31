import { Button } from '@/components/ui/Button';
import { StatusBadge, type StatusCode } from '@/components/ui/StatusBadge';
import type { BoardEntry } from '@/lib/board/types';
import { dataAgeText } from '@/lib/board/format';
import { alertTime, type AlertItem } from '@/lib/exec/alerts';
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

/** The alert row in words: what became of the executive's own alert for this service. */
export function alertRowText(alert: AlertItem | null): string {
  if (alert === null) return 'No alert for this service';
  if (alert.state === 'acknowledged' && alert.acknowledgedAt !== null) return `Acknowledged by you ${alertTime(alert.acknowledgedAt)}`;
  if (alert.state === 'closed') return `Closed, alerted ${alertTime(alert.raisedAt)}`;
  return `${alert.state === 'escalated' ? 'Escalated' : 'New'}, alerted ${alertTime(alert.raisedAt)}`;
}

type Props = {
  entry: BoardEntry;
  now: string;
  coordinationPhone?: string | null;
  /**
   * The executive's latest alert for this service (ExecApp1 screen 2): null when there is none, left out
   * when the alerts could not be read, so no row is made up.
   */
  alert?: AlertItem | null;
  /** Whether the executive has a deputy to escalate to (the alert settings); left out when not read. */
  escalationInPlace?: boolean;
};

export function ServiceDetail({ entry, now, coordinationPhone = null, alert, escalationInPlace }: Props) {
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
      {alert !== undefined || escalationInPlace !== undefined ? (
        <dl className={styles.facts} data-el="EXEC-SERVICE-FACTS">
          {alert !== undefined ? (
            <div className={styles.fact}>
              <dt>Alert</dt>
              <dd>{alertRowText(alert)}</dd>
            </div>
          ) : null}
          {escalationInPlace !== undefined ? (
            <div className={styles.fact}>
              <dt>Escalation in place</dt>
              <dd>{escalationInPlace ? 'Yes' : 'No'}</dd>
            </div>
          ) : null}
        </dl>
      ) : null}
      <div className={styles.actions}>
        {coordinationPhone !== null ? (
          <Button variant="primary" href={telHref(coordinationPhone)} dataEl="EXEC-SERVICE-CALL-LINK">
            Call the duty coordinator
          </Button>
        ) : null}
        <Button variant="secondary" href="/planning/alerts">Back to alerts</Button>
      </div>
      {coordinationPhone !== null ? <p className={styles.footer}>{coordinationPhone}</p> : null}
    </div>
  );
}
