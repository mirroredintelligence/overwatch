import { OrgLabel } from '@/components/scope/OrgLabel';
import { StatusBadge } from '@/components/ui/StatusBadge';
import { ageLineText, categoryLabel, dataAgeText, londonTime } from '@/lib/board/format';
import { toBoardEntry } from '@/lib/network/entries';
import type { NetworkBoardEntry } from '@/lib/network/types';
import { figureFor, LAST_KNOWN_WARNING, lastKnownFigureFor, UNKNOWN_UNIT, VARIANT } from './Tile';
import styles from './Tile.module.css';

// One service of the network board (docs/design/network-ui.md section 4): the wall tile's look and rules for
// the figure, with the organisation under the name, and nothing a network does not share (no comment, no
// pending count, no next-due time). A figure it cannot stand behind is "?" and "Phone to confirm". The one
// control on it is the service line, a link to phone the service. A tile carries opaque references only.

export type ServiceLine = { label: string | null; phone: string | null };
/**
 * `undefined` while they are being read and `null` when they could not be: in both no line is shown, and
 * none is invented ("No number shared" is only for a service whose organisation shared none).
 */
export type ServiceLines = Record<string, ServiceLine> | null | undefined;

const PAUSED_WORDS = 'Not available on the network. Phone to confirm.';

function telHref(phone: string): string {
  return `tel:${phone.replace(/[^0-9+]/g, '')}`;
}

export function isPaused(entry: NetworkBoardEntry): boolean {
  return entry.presentation === 'unavailable' || entry.status === null;
}

/** The line that says how to phone the service, or that no number was shared, or nothing when unknown. */
export function ServiceLineText({ entry, lines }: { entry: NetworkBoardEntry; lines: ServiceLines }) {
  if (lines === null || lines === undefined || isPaused(entry)) return null;
  const line = lines[entry.rowRef];
  if (line?.phone === null || line === undefined) return <p className={styles.meta}>No number shared</p>;
  return (
    <p className={styles.meta}>
      {`${line.label ?? 'Service line'} `}
      <a href={telHref(line.phone)} data-el="NET-BOARD-PHONE-LINK" aria-label={`Phone ${entry.serviceName} on ${line.phone}`}>
        {line.phone}
      </a>
    </p>
  );
}

export function NetworkTile({
  entry,
  now,
  own,
  orgRef,
  lines,
  lastKnown = false,
}: {
  entry: NetworkBoardEntry;
  now: string | Date;
  own: boolean;
  orgRef: string;
  lines: ServiceLines;
  lastKnown?: boolean;
}) {
  const asWall = toBoardEntry(entry);
  const paused = isPaused(entry);
  const figure = paused
    ? { big: '?', unit: UNKNOWN_UNIT, bar: null }
    : lastKnown
      ? lastKnownFigureFor(asWall)
      : figureFor(asWall);
  const variant = lastKnown || paused ? styles.notUpdated : VARIANT[asWall.status];
  const status = lastKnown ? 'last-known' : asWall.status;
  const notUpdated = !lastKnown && asWall.status === 'not-updated';

  return (
    <article
      className={`${styles.tile} ${variant}`}
      data-el="NET-BOARD-TILE"
      data-service-ref={entry.rowRef}
      data-org-ref={orgRef}
      data-status={status}
    >
      <div className={styles.top}>
        <div className={styles.who}>
          <h2 className={styles.name}>{entry.serviceName}</h2>
          <OrgLabel name={entry.organisationName} own={own} />
          <p className={styles.category}>{categoryLabel(entry.category)}</p>
        </div>
        <StatusBadge status={status} size="lg" />
      </div>

      <div className={styles.figure}>
        <p className={styles.number}>{figure.big}</p>
        <div className={styles.words}>
          <p className={styles.unit}>{figure.unit}</p>
          {paused ? (
            <p className={styles.meta}>{PAUSED_WORDS}</p>
          ) : lastKnown ? (
            <p className={styles.meta}>
              {entry.reportedAt === null ? 'No figure reported yet' : `Last known ${londonTime(entry.reportedAt)} · ${dataAgeText(entry.reportedAt, now)}`}
            </p>
          ) : null}
          <ServiceLineText entry={entry} lines={lines} />
        </div>
      </div>

      {figure.bar === null ? null : (
        <div className={styles.usage}>
          <p className={styles.barLabel}>{figure.bar.label}</p>
          <div className={styles.bar} aria-hidden="true">
            <div className={styles.fill} data-bar-fill style={{ width: `${figure.bar.percent}%` }} />
          </div>
        </div>
      )}

      {paused ? null : (
        <p className={styles.age}>{lastKnown ? <strong>{LAST_KNOWN_WARNING}</strong> : notUpdated ? <strong>{ageLineText(asWall, now)}</strong> : ageLineText(asWall, now)}</p>
      )}
    </article>
  );
}

/** One service as a row of the list, at phone width: the same fields in the same order. */
export function NetworkRow({
  entry,
  now,
  own,
  orgRef,
  lines,
  lastKnown = false,
}: {
  entry: NetworkBoardEntry;
  now: string | Date;
  own: boolean;
  orgRef: string;
  lines: ServiceLines;
  lastKnown?: boolean;
}) {
  const asWall = toBoardEntry(entry);
  const paused = isPaused(entry);
  const figure = paused ? { big: '?', unit: UNKNOWN_UNIT, bar: null } : lastKnown ? lastKnownFigureFor(asWall) : figureFor(asWall);
  const status = lastKnown || paused ? (lastKnown ? 'last-known' : 'not-updated') : asWall.status;
  const word = { accepting: 'Accepting', limited: 'Limited', 'not-accepting': 'Not accepting', 'over-capacity': 'Over capacity', 'not-updated': 'Not updated', 'out-of-hours': 'Out of hours', 'last-known': 'Last known' }[status];
  const parts = [categoryLabel(entry.category), word, figure.big, figure.bar?.label ?? null].filter((part): part is string => part !== null);
  return (
    <article className={`${styles.tile} ${lastKnown || paused ? styles.notUpdated : VARIANT[asWall.status]}`} data-el="NET-BOARD-ROW" data-service-ref={entry.rowRef} data-org-ref={orgRef} data-status={status}>
      <h2 className={styles.name}>{entry.serviceName}</h2>
      <OrgLabel name={entry.organisationName} own={own} />
      <p className={styles.barLabel}>{parts.join(' · ')}</p>
      {paused ? <p className={styles.meta}>{PAUSED_WORDS}</p> : <p className={styles.age}>{lastKnown ? <strong>{LAST_KNOWN_WARNING}</strong> : ageLineText(asWall, now)}</p>}
      <ServiceLineText entry={entry} lines={lines} />
    </article>
  );
}
