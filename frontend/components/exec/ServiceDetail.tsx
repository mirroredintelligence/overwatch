import { Button } from '@/components/ui/Button';
import { StatusTag } from '@/components/ui/StatusTag';
import type { BoardEntry } from '@/lib/board/types';
import { categoryLabel, dataAgeText, londonDate, londonTime } from '@/lib/board/format';
import { alertTime, alertTitle, type AlertItem } from '@/lib/exec/alerts';
import { telHref } from '@/lib/exec/call';
import { STATUS_TAG, statusWord } from './PlanningStage';
import styles from './ServiceDetail.module.css';

// One service for the executive (boards/planning/PService.dc.html, the stage of Morph at its second state). The
// figure is the board's own: over established capacity by a count, or what is free. "Call the duty coordinator"
// is shown only when the board holds the tenant's number (DEC-777): no number is made up. The alert for the
// service sits beside it (ServiceAlertCard); the alert unit composes this same card at its own stage.

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

/** Minutes into the London day, from "HH:MM". */
function minutesOfDay(clock: string): number {
  const [hours, minutes] = clock.split(':').map(Number);
  return (hours ?? 0) * 60 + (minutes ?? 0);
}

const percent = (minutes: number) => `${Math.min(100, Math.max(0, (minutes / 1440) * 100)).toFixed(2)}%`;

/**
 * The day so far (the board's "Today" strip). The board holds the last report and the clock, not the status
 * intervals of the day, so the strip marks those two moments and names no interval it does not have.
 */
function Today({ reportedAt, now }: { reportedAt: string; now: string }) {
  const reported = londonTime(reportedAt);
  const current = londonTime(now);
  return (
    <div className={styles.today} role="group" aria-label="Today">
      <div className={styles.eyebrow}>Today</div>
      <div className={styles.strip} role="img" aria-label={`Last reported at ${reported}, now ${current}`}>
        <span className={styles.sofar} style={{ width: percent(minutesOfDay(current)) }} />
        <span className={styles.mark} data-mark="reported" style={{ left: percent(minutesOfDay(reported)) }} />
        <span className={styles.mark} data-mark="now" style={{ left: percent(minutesOfDay(current)) }} />
      </div>
      <div className={styles.ticks}>
        <span>00:00</span>
        <span>{`Last reported ${reported}`}</span>
        <span>{`now ${current}`}</span>
        <span>24:00</span>
      </div>
    </div>
  );
}

/**
 * The alert for this service, beside it (the side column of Morph at its second state): what it says and the
 * one way into it. Null when there is none; left out (undefined) when the alerts could not be read, so no row
 * is made up.
 */
export function ServiceAlertCard({ alert }: { alert: AlertItem | null | undefined }) {
  return (
    <section className={styles.card} aria-label="Alert for this service">
      <div className={styles.eyebrow}>Alert for this service</div>
      {alert === undefined ? (
        <p className={styles.alertTitle}>The alerts could not be read.</p>
      ) : alert === null ? (
        <p className={styles.alertTitle}>{alertRowText(null)}</p>
      ) : (
        <>
          <p className={styles.alertTitle}>{alertTitle(alert)}</p>
          <p className={styles.alertLine}>{alertRowText(alert)}</p>
          <Button variant="primary" href={`/planning/alerts/${encodeURIComponent(alert.id)}`}>
            Open the alert
          </Button>
        </>
      )}
    </section>
  );
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
  const kind = categoryLabel(entry.category);
  const updated = entry.reportedAt === null ? 'no report yet' : `updated ${dataAgeText(entry.reportedAt, now)}`;
  const reportedToday = entry.reportedAt !== null && londonDate(entry.reportedAt) === londonDate(now);
  return (
    <div className={styles.card} data-status={entry.status}>
      <div className={styles.head}>
        <div>
          <h1 className={styles.name}>{entry.name}</h1>
          <p className={styles.sub}>{`${kind} · ${updated}`}</p>
        </div>
        <StatusTag variant={STATUS_TAG[entry.status] ?? 'todo'}>{statusWord(entry.status)}</StatusTag>
      </div>
      {figure ? (
        <section className={styles.figure} aria-label="Figure">
          <p className={styles.big}>{figure.big}</p>
          <div>
            <p className={styles.small}>{figure.small}</p>
            {entry.used !== null ? <p className={styles.used}>{`${entry.used} of ${entry.established} ${entry.unitLabel}`}</p> : null}
          </div>
        </section>
      ) : null}
      {reportedToday && entry.reportedAt !== null ? <Today reportedAt={entry.reportedAt} now={now} /> : null}
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
          <Button variant="secondary" href={telHref(coordinationPhone)} dataEl="EXEC-SERVICE-CALL-LINK">
            Call the duty coordinator
          </Button>
        ) : null}
        <Button variant="neutral" href="/planning/alerts">Back to alerts</Button>
      </div>
      {coordinationPhone !== null ? <p className={styles.footer}>{coordinationPhone}</p> : null}
    </div>
  );
}
