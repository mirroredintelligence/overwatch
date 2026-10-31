import type { ReactNode } from 'react';
import styles from './practitioner.module.css';

// The frame of every practitioner screen (RadarPhone 1 to 4): a bar with a back arrow and the screen's
// name, the page, and the actions at the foot. The back arrow is a link, so it works with no script.

export function PhoneScreen({ title, backHref, children, actions }: { title: string; backHref: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className={styles.screen} aria-label={title}>
      <div className={styles.bar}>
        <a className={styles.back} href={backHref} aria-label="Back" data-el="PRAC-BACK-LINK">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
            <path d="M15 5l-7 7 7 7" />
          </svg>
        </a>
        <p className={styles.barTitle}>{title}</p>
      </div>
      <div className={styles.body}>{children}</div>
      {actions === undefined ? null : <div className={styles.actions}>{actions}</div>}
    </section>
  );
}

/** The word on a visit's urgency, as a screen says it: "Wanted within 2 hrs", "Wanted today". */
export function wantedText(wantedWithin: string): string {
  return wantedWithin === 'planned' ? 'Planned visit' : `Wanted ${wantedWithin}`;
}
