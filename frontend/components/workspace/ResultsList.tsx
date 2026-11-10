'use client';

import Link from 'next/link';
import { useEffect, useRef, useState, type ReactElement } from 'react';
import { ShapeIcon, STATUS_LABELS, STATUS_SHAPES } from '@/components/ui/StatusBadge';
import type { FoundService } from '@/lib/advisor/v2/find';
import { categoryLabel } from '@/lib/board/format';
import { overdueText } from '@/lib/lead/format';
import styles from './ResultsList.module.css';

// The flat list of the found services (AdvisorResults and AdvisorMap boards, DEC-1379): one row for each service in the
// order it is given, as many rows a page as the height holds, with Previous, Next and "a to b of N". The page never
// scrolls. The row heights and the gap below are the ones in ResultsList.module.css (72px and 10px; 64px and 8px for the
// compact rows beside the map), so the count of rows that fit is exact. Where the height cannot be measured every row is
// shown. The page number is not in the URL, so a new list starts again at page 1.

const FULL = { row: 72, gap: 10 } as const;
const COMPACT = { row: 64, gap: 8 } as const;
const DASH = '–';

export type ResultsListProps = {
  services: readonly FoundService[];
  /** The narrow rows beside the map: name, group and the status with its figure. */
  compact?: boolean;
  /** A row was chosen (its link was followed): the page remembers the service for the thread. */
  onOpen: (service: FoundService) => void;
};

function capitalised(text: string): string {
  return text === '' ? text : text.charAt(0).toUpperCase() + text.slice(1);
}

export function serviceHref(serviceId: string): string {
  return `/advisor/v2/services/${encodeURIComponent(serviceId)}`;
}

function updatedText(service: FoundService): string {
  if (service.dataAgeSeconds === null) return 'no report yet';
  const ago = `updated ${overdueText(Math.floor(service.dataAgeSeconds / 60))} ago`;
  return service.figureUnavailable ? `capacity report overdue · ${ago}` : ago;
}

/** The figure to offer, or null when there is none to offer: a late, old or unknown figure is never current capacity. */
function figureOf(service: FoundService): { value: string; unit: string } | null {
  if (service.figureUnavailable) return null;
  if (service.status === 'over-capacity' && service.overBy !== null) return { value: `+${service.overBy}`, unit: 'Above normal' };
  if (service.effectiveAvailable === null) return null;
  return { value: String(service.effectiveAvailable), unit: capitalised(service.unitLabel ?? 'remaining') };
}

function Row({ service, compact, onOpen }: { service: FoundService; compact: boolean; onOpen: (service: FoundService) => void }): ReactElement {
  const figure = figureOf(service);
  return (
    <Link
      href={serviceHref(service.serviceId)}
      className={`${styles.row} ${compact ? styles.compact : ''}`}
      data-figure={figure === null ? 'unavailable' : 'known'}
      data-el="WS-RESULT-ROW"
      onClick={() => onOpen(service)}
    >
      <span className={styles.left}>
        <b className={compact ? styles.nameCompact : styles.name}>{service.name}</b>
        <span className={styles.caption}>
          {compact ? categoryLabel(service.category) : `${categoryLabel(service.category)} · ${updatedText(service)}`}
        </span>
      </span>
      <span className={styles.right}>
        <span className={styles.status} data-status={service.status}>
          <ShapeIcon shape={STATUS_SHAPES[service.status]} />
          {compact && figure !== null ? `${STATUS_LABELS[service.status]} · ${figure.value}` : STATUS_LABELS[service.status]}
        </span>
        {compact ? null : figure === null ? (
          <span className={styles.figure}>
            <span className={styles.srOnly}>Current capacity unavailable</span>
            <span className={styles.unknownNumber} aria-hidden="true">
              ?
            </span>
            <span className={styles.unit} aria-hidden="true">
              Unknown
            </span>
          </span>
        ) : (
          <span className={styles.figure}>
            <span className={styles.number}>{figure.value}</span>
            <span className={styles.unit}>{figure.unit}</span>
          </span>
        )}
        {compact ? null : (
          <span className={styles.open} aria-hidden="true">
            Open
          </span>
        )}
      </span>
    </Link>
  );
}

export function ResultsList({ services, compact = false, onOpen }: ResultsListProps): ReactElement {
  const { row, gap } = compact ? COMPACT : FULL;
  const viewport = useRef<HTMLDivElement>(null);
  const [rows, setRows] = useState<number | null>(null);
  // The page belongs to the list it was chosen in: another list (another order) starts at the first page.
  const listKey = services.map((service) => service.serviceId).join('|');
  const [chosen, setChosen] = useState<{ key: string; page: number }>({ key: listKey, page: 0 });

  useEffect(() => {
    const element = viewport.current;
    if (element === null || typeof ResizeObserver === 'undefined') return;
    const measure = () => {
      const height = element.clientHeight;
      setRows(height > 0 ? Math.max(1, Math.floor((height + gap) / (row + gap))) : null);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [row, gap]);

  const perPage = rows === null ? Math.max(1, services.length) : rows;
  const pages = Math.max(1, Math.ceil(services.length / perPage));
  const page = Math.min(chosen.key === listKey ? chosen.page : 0, pages - 1);
  const first = page * perPage;
  const shown = services.slice(first, first + perPage);

  return (
    <div className={styles.root}>
      <div ref={viewport} className={styles.viewport} data-el="WS-RESULTS-VIEWPORT">
        <ul className={`${styles.list} ${compact ? styles.listCompact : ''}`} aria-label="Matching services">
          {shown.map((service) => (
            <li key={service.serviceId}>
              <Row service={service} compact={compact} onOpen={onOpen} />
            </li>
          ))}
        </ul>
      </div>
      {services.length === 0 ? null : (
        <nav className={styles.pager} aria-label="Matching services pages">
          <span aria-live="polite" data-el="WS-RESULTS-COUNT">{`${first + 1}${DASH}${first + shown.length} of ${services.length}`}</span>
          <span className={styles.pages}>
            <button type="button" className={styles.page} disabled={page === 0} aria-label="Previous page" onClick={() => setChosen({ key: listKey, page: page - 1 })}>
              Previous
            </button>
            <button type="button" className={styles.page} disabled={page >= pages - 1} aria-label="Next page" onClick={() => setChosen({ key: listKey, page: page + 1 })}>
              Next
            </button>
          </span>
        </nav>
      )}
    </div>
  );
}
