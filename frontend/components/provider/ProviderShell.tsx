'use client';

import { useEffect, useRef, type ReactNode } from 'react';
import { SetupProgress } from './SetupProgress';
import { StickyAction, type StickyActionProps } from './StickyAction';
import styles from './ProviderShell.module.css';

export type ProviderShellProps = {
  /** The service the person is setting up: shown as the chip in the top bar. */
  service?: string | null;
  /** Current step, 1 to 5. Omit on pages that are not a step (an expired link). */
  step?: number;
  action?: StickyActionProps;
  children: ReactNode;
};

// The phone frame for the invitation, set-up and register pages: a top bar (mark and service chip), the
// progress, the content and the sticky action. On a wide screen the same column is 480px, centred.
// When the step changes, focus moves to the heading of the new step (not on first render).
export function ProviderShell({ service, step, action, children }: ProviderShellProps) {
  const content = useRef<HTMLElement>(null);
  const previous = useRef(step);

  useEffect(() => {
    if (previous.current === step) return;
    previous.current = step;
    const heading = content.current?.querySelector<HTMLElement>('h1');
    if (!heading) return;
    if (!heading.hasAttribute('tabindex')) heading.setAttribute('tabindex', '-1');
    heading.focus({ preventScroll: false });
  }, [step]);

  return (
    <div className={styles.page}>
      <div className={styles.column}>
        <header className={styles.top}>
          <div className={styles.brand}>
            <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true">
              <circle cx="13" cy="13" r="10" fill="none" stroke="#fff" strokeWidth="2.4" />
              <circle cx="13" cy="13" r="4.2" fill="#fff" />
              <path d="M3 13h20" stroke="#fff" strokeWidth="2.4" />
            </svg>
            Overwatch
          </div>
          {service ? (
            <span className={styles.chip} data-chip>
              {service}
            </span>
          ) : null}
        </header>
        {step !== undefined ? <SetupProgress step={step} /> : null}
        <main ref={content} className={styles.content}>
          {children}
        </main>
        {action ? <StickyAction {...action} /> : null}
      </div>
    </div>
  );
}
