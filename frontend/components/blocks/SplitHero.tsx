import type { ReactNode } from 'react';
import styles from './SplitHero.module.css';

// The split used by sign-in (admin O1, staff, phone Ph1) and home (P1): a dark brand half with the product name,
// eyebrow, title, lead and footnote, and a light half that holds the page's card. Under 40rem the brand half is a
// short band above the card, and it loses its lead and footnote as the phone board shows.

export type SplitHeroProps = {
  eyebrow?: ReactNode;
  title: ReactNode;
  lead?: ReactNode;
  footnote?: ReactNode;
  // Which half the brand sits in on wide screens. Home shows it on the right; sign-in keeps it on the left.
  brandAt?: 'start' | 'end';
  contentLabel?: string;
  children?: ReactNode;
};

export function SplitHero({ eyebrow, title, lead, footnote, brandAt = 'start', contentLabel = 'Sign in', children }: SplitHeroProps) {
  return (
    <div className={styles.root} data-brand-at={brandAt}>
      <section aria-label="Overwatch" className={styles.brand}>
        <div className={styles.brandTop}>
          <span className={styles.mark}>
            <svg viewBox="0 0 26 26" aria-hidden="true">
              <circle cx="13" cy="13" r="10" fill="none" stroke="#fff" strokeWidth="2.4" />
              <circle cx="13" cy="13" r="4.2" fill="#fff" />
              <path d="M3 13h20" stroke="#fff" strokeWidth="2.4" />
            </svg>
          </span>
          Overwatch
        </div>
        <div className={styles.middle}>
          {eyebrow ? <div className={styles.eyebrow}>{eyebrow}</div> : null}
          <h1 className={styles.title}>{title}</h1>
          {lead ? <p className={styles.lead}>{lead}</p> : null}
        </div>
        {footnote ? <div className={styles.footnote}>{footnote}</div> : null}
      </section>
      <section aria-label={contentLabel} className={styles.content}>
        <div className={styles.inner}>{children}</div>
      </section>
    </div>
  );
}
