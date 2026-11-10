import styles from './Analytics.module.css';

// "1–6 of 8 services" with Previous and Next. The buttons are shown only when there is more than one page.

export const PAGE_SIZE = 6;

export function pageOf<T>(items: readonly T[], page: number, size: number): T[] {
  return items.slice(page * size, page * size + size);
}

export function plural(n: number, one: string, many: string): string {
  return n === 1 ? one : many;
}

export function Pager({ total, page, size, noun, onPage }: { total: number; page: number; size: number; noun: string; onPage: (page: number) => void }) {
  if (total === 0) return null;
  const first = page * size + 1;
  const last = Math.min(total, page * size + size);
  const pages = Math.ceil(total / size);
  return (
    <div className={styles.pager}>
      <p className={styles.pagerText} role="status">{`${first}–${last} of ${total} ${noun}`}</p>
      {pages > 1 ? (
        <div className={styles.pagerButtons}>
          <button type="button" className={styles.pagerButton} disabled={page === 0} onClick={() => onPage(page - 1)}>
            Previous
          </button>
          <button type="button" className={styles.pagerButton} disabled={page >= pages - 1} onClick={() => onPage(page + 1)}>
            Next
          </button>
        </div>
      ) : null}
    </div>
  );
}
