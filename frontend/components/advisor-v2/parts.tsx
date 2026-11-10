'use client';

import Link from 'next/link';
import { type ReactNode, useEffect, useRef, useState } from 'react';
import { ShapeIcon, STATUS_LABELS, STATUS_SHAPES, type StatusCode } from '@/components/ui/StatusBadge';
import { attentionClass, attentionOf } from '@/lib/attention';
import type { OptionView } from '@/lib/advisor/options';
import { lastReportedLine } from '@/lib/advisor/reporting';
import { categoryLabel } from '@/lib/board/format';
import { overdueText } from '@/lib/lead/format';
import styles from './V2.module.css';

// The pieces the Advisor v2 views share (DEC-1366), in the look of the SPoA design: a status dot with its word, a
// paged grid that shows as many rows as fit and never scrolls the page, and the service tile.

const DOT: Record<StatusCode, string> = {
  accepting: styles.accepting,
  limited: styles.limited,
  'not-accepting': styles.notAccepting,
  'over-capacity': styles.overCapacity,
  'not-updated': styles.notUpdated,
  'out-of-hours': styles.outOfHours,
  'last-known': styles.lastKnown,
};

/** The coloured dot. It is decoration: the status word always sits beside it. */
export function Dot({ status }: { status: StatusCode }) {
  return <span className={`${styles.dot} ${DOT[status]}`} aria-hidden="true" />;
}

export function Lozenge({ status }: { status: StatusCode }) {
  return (
    <span className={styles.lozenge}>
      <Dot status={status} />
      {STATUS_LABELS[status]}
    </span>
  );
}

const ROW = 92;
const TALL_ROW = 124;
const GAP = 8;

/**
 * A grid of cards in pages. The page holds as many rows as the height allows (each row is 84px); when the height
 * cannot be measured every item is shown. Previous and Next move between pages, and the count says where you are.
 */
export function PagedGrid<T>({
  items,
  render,
  keyOf,
  label,
  noun,
  cols = 1,
  tall = false,
  empty,
}: {
  items: readonly T[];
  render: (item: T) => ReactNode;
  keyOf: (item: T) => string;
  label: string;
  noun: string;
  cols?: 1 | 2 | 3;
  /** Taller rows, for the location cards. */
  tall?: boolean;
  empty: string;
}) {
  const gridRef = useRef<HTMLUListElement>(null);
  const [fit, setFit] = useState<{ rows: number; columns: number } | null>(null);
  const [page, setPage] = useState(0);

  useEffect(() => {
    const grid = gridRef.current;
    if (grid === null || typeof ResizeObserver === 'undefined') return;
    const measure = () => {
      const height = grid.clientHeight;
      // The columns are what the stylesheet gives at this width (a narrow screen has fewer than `cols`).
      const columns = Math.max(1, getComputedStyle(grid).gridTemplateColumns.split(' ').filter((part) => part !== '').length);
      setFit(height > 0 ? { rows: Math.max(1, Math.floor((height + GAP) / ((tall ? TALL_ROW : ROW) + GAP))), columns } : null);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(grid);
    return () => observer.disconnect();
  }, [tall]);

  const perPage = fit === null ? Math.max(1, items.length) : fit.rows * fit.columns;
  const pages = Math.max(1, Math.ceil(items.length / perPage));
  const current = Math.min(page, pages - 1);
  const shown = items.slice(current * perPage, current * perPage + perPage);

  return (
    <div className={styles.collection}>
      <ul ref={gridRef} className={`${styles.grid} ${cols === 3 ? styles.cols3 : cols === 2 ? styles.cols2 : styles.cols1} ${tall ? styles.tall : ''}`} aria-label={label}>
        {items.length === 0 ? (
          <li className={styles.empty}>{empty}</li>
        ) : (
          shown.map((item) => <li key={keyOf(item)}>{render(item)}</li>)
        )}
      </ul>
      <nav className={`${styles.pager} ${pages === 1 ? styles.pagerSingle : ''}`} aria-label={`${label} pages`}>
        <span className={styles.pagerCount} aria-live="polite">
          {items.length === 0 ? '' : pages === 1 ? `${items.length} ${noun}` : `Page ${current + 1} of ${pages} · ${items.length} ${noun}`}
        </span>
        <span className={styles.pagerActions}>
          <button type="button" className={styles.pagerButton} disabled={current === 0} onClick={() => setPage(current - 1)} aria-label="Previous page">
            Previous
          </button>
          <button type="button" className={styles.pagerButton} disabled={current >= pages - 1} onClick={() => setPage(current + 1)} aria-label="Next page">
            Next
          </button>
        </span>
      </nav>
    </div>
  );
}

function updatedText(option: OptionView): string {
  if (option.dataAgeSeconds === null) return 'No report yet';
  const age = `${overdueText(Math.floor(option.dataAgeSeconds / 60))} ago`;
  return option.figureUnavailable ? `Overdue · ${age}` : `Updated ${age}`;
}

/**
 * One service as a tile (the design's `service` card): name, group, status word beside its dot, when it was updated,
 * and the capacity on the right. A late, old or unknown figure reads "Current capacity unavailable" with the last
 * figure small, never as a number to offer (DEC-1343). The whole tile links to the service's page.
 */
export function ServiceTile({ option }: { option: OptionView }) {
  const unavailable = option.figureUnavailable;
  const over = option.status === 'over-capacity' && option.overBy !== null;
  const value = over ? `+${option.overBy}` : option.effectiveAvailable === null ? null : String(option.effectiveAvailable);
  const unit = option.unitLabel ?? '';
  const unitWords = over ? 'above normal' : unit === '' ? 'remaining' : unit;
  const readOut = unavailable || value === null ? 'Current capacity unavailable' : `${value} ${unitWords}`;
  return (
    <Link
      className={`${styles.service} ${attentionClass(attentionOf({ status: option.status, stale: option.figureUnavailable }))}`}
      href={`/advisor/v2/services/${encodeURIComponent(option.serviceId)}`}
      aria-label={`${option.name}, ${STATUS_LABELS[option.status]}, ${readOut}`}
      data-el="ADV2-SERVICE"
    >
      <span>
        <span className={styles.serviceTitle}>{option.name}</span>
        <span className={styles.serviceSub}>
          {option.category === null ? null : <span>{categoryLabel(option.category)}</span>}
          <Lozenge status={option.status} />
          <span className={unavailable ? styles.late : undefined}>{updatedText(option)}</span>
          {option.travelText === null ? null : <span>{option.travelText}</span>}
        </span>
      </span>
      <span className={styles.cap}>
        {unavailable || value === null ? (
          <>
            <b className={styles.unknown}>Current capacity unavailable</b>
            <small>{lastReportedLine(option)}</small>
          </>
        ) : (
          <>
            <small>{unitWords}</small>
            <b>{value}</b>
          </>
        )}
      </span>
    </Link>
  );
}

const RING_STATUSES = ['accepting', 'limited', 'not-accepting', 'over-capacity', 'not-updated'] as const;
const RADIUS = 42;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

/** A ring of a place's services by state. A picture only; the same counts are written beside it in StatusLegend. */
export function StatusRing({ tally }: { tally: Record<(typeof RING_STATUSES)[number], number> }) {
  const total = RING_STATUSES.reduce((sum, status) => sum + tally[status], 0);
  // Where each segment starts: the services before it, as a share of the circle.
  const starts = RING_STATUSES.map((_, index) => RING_STATUSES.slice(0, index).reduce((sum, status) => sum + tally[status], 0));
  return (
    <svg className={styles.ring} viewBox="0 0 100 100" aria-hidden="true" focusable="false">
      {total === 0 ? <circle className={styles.ringSeg} data-status="none" cx="50" cy="50" r={RADIUS} strokeWidth="14" /> : null}
      {RING_STATUSES.map((status, index) => {
        const n = tally[status];
        if (n === 0) return null;
        const length = (CIRCUMFERENCE * n) / total;
        return (
          <circle
            key={status}
            className={styles.ringSeg}
            data-status={status}
            cx="50"
            cy="50"
            r={RADIUS}
            strokeWidth="14"
            strokeDasharray={`${Math.max(0, length - (total > n ? 2 : 0))} ${CIRCUMFERENCE}`}
            strokeDashoffset={-((CIRCUMFERENCE * (starts[index] ?? 0)) / total)}
            transform="rotate(-90 50 50)"
          />
        );
      })}
    </svg>
  );
}

/** The counts of the ring in words, each beside its shape: no meaning rests on colour. */
export function StatusLegend({ tally }: { tally: Record<(typeof RING_STATUSES)[number], number> }) {
  const shown = RING_STATUSES.filter((status) => tally[status] > 0);
  return (
    <ul className={styles.legend}>
      {shown.length === 0 ? <li className={styles.legendItem}>No services</li> : null}
      {shown.map((status) => (
        <li key={status} className={styles.legendItem}>
          <span className={styles.shape}>
            <ShapeIcon shape={STATUS_SHAPES[status]} />
          </span>
          {`${tally[status]} ${STATUS_LABELS[status]}`}
        </li>
      ))}
    </ul>
  );
}
