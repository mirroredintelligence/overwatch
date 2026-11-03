import type { ReactNode } from 'react';
import { Loading, Skeleton } from '@/components/ui/Skeleton';
import styles from './practitioner.module.css';

// The frame of every practitioner screen (B10, B11): a dark bar with a back arrow and the screen's name, the
// page, and the actions at the foot over a fade. The back arrow is a link, so it works with no script.

export function PhoneScreen({ title, backHref, children, actions }: { title: string; backHref: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className={styles.screen} aria-label={title}>
      <div className={styles.bar}>
        <a className={styles.back} href={backHref} aria-label="Back" data-el="PRAC-BACK-LINK">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
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

/** A screen that is still opening: one shimmer over the shapes of what is coming, and the words for a screen reader. */
export function PhoneOpening({ title, backHref, label }: { title: string; backHref: string; label: string }) {
  return (
    <PhoneScreen title={title} backHref={backHref}>
      <Loading label={label}>
        <div className={styles.shimmer}>
          <Skeleton shape="title" width="60%" />
          <Skeleton shape="block" />
          <Skeleton shape="block" />
        </div>
      </Loading>
    </PhoneScreen>
  );
}

/** A screen that could not load: what happened, in plain words. */
export function PhoneFailed({ title, backHref, children }: { title: string; backHref: string; children: ReactNode }) {
  return (
    <PhoneScreen title={title} backHref={backHref}>
      <p className={styles.failed}>{children}</p>
    </PhoneScreen>
  );
}

/** The word on a visit's urgency, as a screen says it: "Wanted within 2 hrs", "Wanted today". */
export function wantedText(wantedWithin: string): string {
  return wantedWithin === 'planned' ? 'Planned visit' : `Wanted ${wantedWithin}`;
}

/** The same, as a short line under a visit: "Within 2 hrs", "Today", "Planned". */
export function whenText(wantedWithin: string): string {
  return wantedWithin === 'planned' ? 'Planned' : wantedWithin.charAt(0).toUpperCase() + wantedWithin.slice(1);
}
