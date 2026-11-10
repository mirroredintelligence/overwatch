'use client';

import Link from 'next/link';
import { type ReactElement, useEffect, useRef, useState } from 'react';
import { STATUS_LABELS, type StatusCode } from '@/components/ui/StatusBadge';
import type { NotSuitable } from '@/lib/advisor/v2/find';
import { categoryLabel } from '@/lib/board/format';
import styles from './NotSuitableList.module.css';

// The services that were not suitable, each with every reason and its status (AdvisorWhy board, DEC-1379). The rows are
// paged to the height the list has, so the page never scrolls; with no measurable height every row is shown.

export type NotSuitableListProps = {
  items: readonly NotSuitable[];
  /** How many services were suitable, for "Back to the N suitable services". */
  suitableCount: number;
  /** The summary line of the criteria, for the sub-heading (for example "65 to 79 · DT4 · Frailty · Today"). */
  summaryLine: string | null;
  /** Opens a service's page. */
  serviceHref: (serviceId: string) => string;
  /** Where "Back to the N suitable services" goes. */
  backHref: string;
};

// The height a row takes, from the stylesheet: its padding and at least the name and category; each reason is a line.
const ROW_MIN = 72;
const ROW_PAD = 24;
const REASON_LINE = 23;
const GAP = 10;

const rowHeight = (item: NotSuitable): number => Math.max(ROW_MIN, ROW_PAD + item.reasons.length * REASON_LINE);

const DOT: Record<StatusCode, string> = {
  accepting: styles.accepting,
  limited: styles.limited,
  'not-accepting': styles.notAccepting,
  'over-capacity': styles.overCapacity,
  'not-updated': styles.unknown,
  'out-of-hours': styles.unknown,
  'last-known': styles.unknown,
};

/** The pages of rows: a page takes rows while they fit in `height`, and always at least one. A null height is one page. */
function pagesOf(items: readonly NotSuitable[], height: number | null): NotSuitable[][] {
  if (height === null) return [items.slice()];
  const pages: NotSuitable[][] = [];
  let page: NotSuitable[] = [];
  let used = 0;
  for (const item of items) {
    const need = rowHeight(item) + (page.length === 0 ? 0 : GAP);
    if (page.length > 0 && used + need > height) {
      pages.push(page);
      page = [];
      used = 0;
    }
    used += rowHeight(item) + (page.length === 0 ? 0 : GAP);
    page.push(item);
  }
  pages.push(page);
  return pages;
}

export function NotSuitableList({ items, suitableCount, summaryLine, serviceHref, backHref }: NotSuitableListProps): ReactElement {
  const listRef = useRef<HTMLUListElement>(null);
  const [height, setHeight] = useState<number | null>(null);
  const [page, setPage] = useState(0);

  useEffect(() => {
    const list = listRef.current;
    if (list === null || typeof ResizeObserver === 'undefined') return;
    const measure = () => setHeight(list.clientHeight > 0 ? list.clientHeight : null);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(list);
    return () => observer.disconnect();
  }, [items.length]);

  const pages = pagesOf(items, height);
  const current = Math.min(page, pages.length - 1);
  const shown = pages[current] ?? [];
  const first = pages.slice(0, current).reduce((sum, earlier) => sum + earlier.length, 0);

  const heading = items.length === 1 ? '1 service was not suitable for this patient' : `${items.length} services were not suitable for this patient`;
  const hidden = 'Nothing is hidden: every service is either on the results list or here with its reason.';
  // With no suitable service there is nothing to count: the link says so as the thread's chip does.
  const back =
    suitableCount === 0 ? 'Back to the results' : `Back to the ${suitableCount} suitable ${suitableCount === 1 ? 'service' : 'services'}`;

  return (
    <section className={styles.root} aria-label="Services that were not suitable">
      {items.length === 0 ? (
        <p className={styles.empty}>Every service takes this patient. Nothing is hidden.</p>
      ) : (
        <>
          <header className={styles.head}>
            <h1 className={styles.title}>{heading}</h1>
            <p className={styles.sub}>{summaryLine === null ? hidden : `${summaryLine}. ${hidden}`}</p>
          </header>
          <ul ref={listRef} className={styles.list} aria-label="Not suitable services">
            {shown.map((item) => (
              <li key={item.serviceId} className={styles.row}>
                <div className={styles.who}>
                  <Link className={styles.name} href={serviceHref(item.serviceId)}>
                    {item.name}
                  </Link>
                  <span className={styles.category}>{categoryLabel(item.category)}</span>
                </div>
                <div className={styles.why}>
                  {item.reasons.map((reason) => (
                    <span key={reason} className={styles.reason} data-testid="reason">
                      {reason}
                    </span>
                  ))}
                </div>
                <span className={styles.status}>
                  <span className={`${styles.dot} ${DOT[item.status]}`} aria-hidden="true" />
                  {STATUS_LABELS[item.status]}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
      <nav className={styles.foot} aria-label="Not suitable services pages">
        <span className={styles.count} aria-live="polite">
          {items.length === 0 ? '' : `${first + 1}–${first + shown.length} of ${items.length}`}
        </span>
        <span className={styles.actions}>
          {pages.length > 1 ? (
            <>
              <button type="button" className={styles.button} disabled={current === 0} onClick={() => setPage(current - 1)} aria-label="Previous page">
                Previous
              </button>
              <button type="button" className={styles.button} disabled={current >= pages.length - 1} onClick={() => setPage(current + 1)} aria-label="Next page">
                Next
              </button>
            </>
          ) : null}
          <Link className={styles.button} href={backHref}>
            {back}
          </Link>
        </span>
      </nav>
    </section>
  );
}
