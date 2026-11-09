import type { ReactNode } from 'react';
import styles from './Skeleton.module.css';

// Loading placeholders (the shimmer itself is app/skeleton.css). `Loading` wraps the placeholders of one thing that
// is loading and says what in words for people who cannot see them (a polite status, busy until it is replaced),
// so a screen reader hears "Loading the groups." and not a row of empty shapes. The shapes are decoration.
//
//   <Loading label="Loading the groups.">
//     <SkeletonRows count={3} />
//   </Loading>

export function Loading({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className={styles.loading} role="status" aria-busy="true" data-skeleton>
      <span className={styles.srOnly}>{label}</span>
      <div aria-hidden="true" className={styles.shapes}>
        {children}
      </div>
    </div>
  );
}

type Shape = 'line' | 'title' | 'chip' | 'avatar' | 'block';

/** One placeholder shape. `width` is a percentage ("46%"); it is rounded to a whole percent and set by a data
    attribute that Skeleton.module.css reads, because the content security policy refuses a style attribute in the markup. */
export function Skeleton({ shape = 'line', width }: { shape?: Shape; width?: string }) {
  const percent = width === undefined ? NaN : Math.round(Number.parseFloat(width));
  const wide = Number.isFinite(percent) ? Math.min(100, Math.max(1, percent)) : undefined;
  return <span className={`${styles.sk} ${styles[shape]}`} data-w={wide} />;
}

/** A row like the ones the admin pages list: an avatar, two lines and a button-sized block. */
export function SkeletonRows({ count = 3 }: { count?: number }) {
  return (
    <div className={styles.rows}>
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className={styles.row}>
          <Skeleton shape="avatar" />
          <div className={styles.rowText}>
            <Skeleton shape="title" width={`${58 - (index % 3) * 9}%`} />
            <Skeleton shape="line" width={`${82 - (index % 2) * 14}%`} />
          </div>
          <Skeleton shape="chip" />
        </div>
      ))}
    </div>
  );
}
