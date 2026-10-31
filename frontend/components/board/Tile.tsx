import { StatusBadge } from '@/components/ui/StatusBadge';
import { ageLineText, categoryLabel, dataAgeText, londonTime, reopensText } from '@/lib/board/format';
import type { BoardEntry, BoardStatus } from '@/lib/board/types';
import styles from './Tile.module.css';

// One service on the wall board (ui-screens.md, artboards "Main", "TileStates",
// "BoardSurge" and "BoardQuiet"). It shows only what the back end sent for this
// service, and it shows "?" and "Phone to confirm" rather than a number it cannot
// stand behind. Every status has a word and a shape as well as a colour. The tile
// never shows a back-end id except the one data attribute the prompt asks for, and
// never a name or id of any organisation: it is given one service's own figures.

export const VARIANT: Record<BoardStatus, string> = {
  accepting: styles.accepting,
  limited: styles.limited,
  'not-accepting': styles.notAccepting,
  'over-capacity': styles.overCapacity,
  'not-updated': styles.notUpdated,
  'out-of-hours': styles.outOfHours,
};

export type Figure = {
  /** The big number. */
  big: string;
  unit: string;
  /** The line above the bar ("Used N of M", or the status word) and how full the bar is. */
  bar: { label: string; percent: number };
};

export const UNKNOWN_UNIT = 'Phone to confirm';
const OUT_OF_HOURS_LABEL = 'Out of hours';

function usedLabel(used: number | null, established: number): string {
  return `Used ${used === null ? '?' : used} of ${established}`;
}

/** Used over established as a percentage, kept between 0 and 100 and to one decimal place. */
function fillPercent(used: number | null, established: number): number {
  if (used === null) return 0;
  if (established <= 0) return used > 0 ? 100 : 0;
  return Math.round(Math.min(100, Math.max(0, (used / established) * 100)) * 10) / 10;
}

function unknownFigure(established: number): Figure {
  return { big: '?', unit: UNKNOWN_UNIT, bar: { label: usedLabel(null, established), percent: 100 } };
}

export function figureFor(entry: BoardEntry): Figure {
  const { status, established, used } = entry;

  if (status === 'not-updated') {
    // Whatever the back end last held, the figure is not to be relied on.
    return unknownFigure(established);
  }
  if (status === 'out-of-hours') {
    // Closed: no places, whatever figure the service held when it closed (W07, DEC-169 item 3).
    return { big: '0', unit: entry.unitLabel, bar: { label: OUT_OF_HOURS_LABEL, percent: 100 } };
  }

  const bar = { label: usedLabel(used, established), percent: fillPercent(used, established) };

  if (status === 'over-capacity') {
    const over = entry.overBy ?? (used !== null && used > established ? used - established : null);
    return over === null
      ? { big: '?', unit: UNKNOWN_UNIT, bar }
      : { big: `+${over}`, unit: entry.unitLabel, bar };
  }

  // Accepting, limited, not accepting. A service that reports occupancy has no
  // free count of its own, so it is worked out from the two figures the back end gave.
  const free = entry.effectiveAvailable ?? (used === null ? null : Math.max(0, established - used));
  return free === null
    ? { big: '?', unit: UNKNOWN_UNIT, bar }
    : { big: String(free), unit: entry.unitLabel, bar };
}

/**
 * The figure of a tile that is shown as last known. The number stays as the last
 * report left it. A service that was not updated stays "?", and an out-of-hours
 * claim is not repeated, because opening hours may have started or ended since.
 */
export function lastKnownFigureFor(entry: BoardEntry): Figure {
  return entry.status === 'not-updated' || entry.status === 'out-of-hours'
    ? unknownFigure(entry.established)
    : figureFor(entry);
}

export const LAST_KNOWN_WARNING = 'Do not rely on this. Phone to confirm.';

export function Tile({
  entry,
  now,
  lastKnown = false,
}: {
  entry: BoardEntry;
  now: string | Date;
  /** Shows the tile as last known: never styled or worded as current (W06). */
  lastKnown?: boolean;
}) {
  const figure = lastKnown ? lastKnownFigureFor(entry) : figureFor(entry);
  const age = ageLineText(entry, now);
  const notUpdated = entry.status === 'not-updated';
  // Pending is a count of requests not yet answered, shown apart from the number and
  // never taken off it (domain-rules 1.6). A last known tile shows none: the count
  // is as old as the figures, and the tile must not look as if any of it were current.
  const pending = lastKnown ? 0 : entry.pending;
  const barLabel = pending > 0 ? `${figure.bar.label} · ${pending} pending` : figure.bar.label;
  const variant = lastKnown ? styles.notUpdated : VARIANT[entry.status];

  return (
    <article
      className={`${styles.tile} ${variant}`}
      data-el="WALL-TILE"
      data-service-id={entry.serviceId}
      data-status={lastKnown ? 'last-known' : entry.status}
    >
      <div className={styles.top}>
        <div className={styles.who}>
          <h2 className={styles.name}>{entry.name}</h2>
          <p className={styles.category}>{categoryLabel(entry.category)}</p>
        </div>
        <StatusBadge status={lastKnown ? 'last-known' : entry.status} size="lg" />
      </div>

      <div className={styles.figure}>
        <p className={styles.number} data-el="WALL-TILE-NUMBER">
          {figure.big}
        </p>
        {pending > 0 ? (
          <span className={styles.pending} data-el="WALL-TILE-PENDING">
            {`${pending} pending`}
          </span>
        ) : null}
        <div className={styles.words}>
          <p className={styles.unit}>{figure.unit}</p>
          {lastKnown ? (
            <p className={styles.meta} data-el="WALL-TILE-LAST-KNOWN">
              {entry.reportedAt === null ? (
                'No figure reported yet'
              ) : (
                <>
                  <span>{`Last known ${londonTime(entry.reportedAt)}`}</span>
                  <span>{` · ${dataAgeText(entry.reportedAt, now)}`}</span>
                </>
              )}
            </p>
          ) : entry.status === 'out-of-hours' ? (
            // The service's own comment is left out: it may describe hours that no longer apply.
            entry.nextDueAt === null ? null : (
              <p className={styles.meta} data-el="WALL-TILE-REOPENS">
                {reopensText(entry.nextDueAt, now)}
              </p>
            )
          ) : entry.comment ? (
            <p className={styles.comment} data-el="WALL-TILE-COMMENT">
              {entry.comment}
            </p>
          ) : null}
        </div>
      </div>

      <div className={styles.usage}>
        <p className={styles.barLabel}>{barLabel}</p>
        <div className={styles.bar} aria-hidden="true">
          <div className={styles.fill} data-bar-fill style={{ width: `${figure.bar.percent}%` }} />
        </div>
      </div>

      <p className={styles.age}>{lastKnown ? <strong>{LAST_KNOWN_WARNING}</strong> : notUpdated ? <strong>{age}</strong> : age}</p>
    </article>
  );
}
