'use client';

import Link from 'next/link';
import { useSyncExternalStore, type ReactNode } from 'react';
import { ProviderShell } from '@/components/provider/ProviderShell';
import type { StickyActionProps } from '@/components/provider/StickyAction';
import { StageArea, StageGrid, StageLayer } from '@/components/ui/StageGrid';
import { RegistrationChecklist, type ChecklistState } from './RegistrationChecklist';
import { StepHelp } from './StepHelp';
import styles from './RegisterStage.module.css';

// The frame every register page sits in (Reg board): a top bar with "Save and come back later", then a
// StageGrid of list (the checklist), stage (the page) and side (why we ask). Stage 0 is the start page, 1 to 5
// the sections, 6 the submitted page. Each route renders its own stage; the page owns the stage number.
// On a phone the same page is the ProviderShell: progress, the step, a "Why we ask" disclosure, a sticky action.

export const REGISTER_LATER_HREF = '/register?saved=1';

const SIDE = '300px';
const LIST = '300px';
const TEMPLATES = [
  `${LIST} minmax(0,1fr) 0px`,
  `${LIST} minmax(0,1fr) ${SIDE}`,
  `${LIST} minmax(0,1fr) ${SIDE}`,
  `${LIST} minmax(0,1fr) ${SIDE}`,
  `${LIST} minmax(0,1fr) ${SIDE}`,
  `${LIST} minmax(0,1fr) 0px`,
  '0px minmax(0,1fr) 0px',
] as const;
const GAPS = ['var(--space-5)', 'var(--space-5)', 'var(--space-5)', 'var(--space-5)', 'var(--space-5)', 'var(--space-5)', '0px'] as const;
const SUBMITTED = 6;

const PHONE_QUERY = '(max-width: 899px)';

function subscribe(onChange: () => void) {
  if (typeof window.matchMedia !== 'function') return () => {};
  const query = window.matchMedia(PHONE_QUERY);
  query.addEventListener('change', onChange);
  return () => query.removeEventListener('change', onChange);
}

const isPhone = () => typeof window.matchMedia === 'function' && window.matchMedia(PHONE_QUERY).matches;

export type RegisterStageProps = {
  registrationId: string;
  /** 0 start, 1 to 5 the sections, 6 submitted. */
  stage: number;
  /** The service being registered, when the page knows it: shown in the top bar. */
  service?: string | null;
  /** A section's state where it is not the default for the stage (for example 3: 'needs-attention'). */
  states?: Partial<Record<number, ChecklistState>>;
  /** "Saved a moment ago" and the like, beside Save and come back later. */
  savedNote?: string;
  /** The phone's sticky action; Save and come back later is added as its link when it has none. */
  phoneAction?: StickyActionProps;
  children: ReactNode;
};

export function RegisterStage({ registrationId, stage, service, states, savedNote, phoneAction, children }: RegisterStageProps) {
  const phone = useSyncExternalStore(subscribe, isPhone, () => false);
  const clamped = Math.min(Math.max(Math.trunc(stage), 0), SUBMITTED);
  const submitted = clamped === SUBMITTED;

  if (phone) {
    const later = { label: 'Save and come back later', href: REGISTER_LATER_HREF };
    const action = phoneAction ? { ...phoneAction, link: phoneAction.link ?? (submitted ? undefined : later) } : undefined;
    return (
      <ProviderShell service={service} step={clamped >= 1 && clamped <= 5 ? clamped : undefined} action={action}>
        <StepHelp step={clamped} variant="disclosure" />
        {children}
        {!action && !submitted ? (
          <p className={styles.phoneLater}>
            <Link href={later.href}>{later.label}</Link>
          </p>
        ) : null}
      </ProviderShell>
    );
  }

  return (
    <div className={styles.page}>
      <header className={styles.top}>
        <div className={styles.brand}>
          <svg width="30" height="30" viewBox="0 0 26 26" aria-hidden="true">
            <circle cx="13" cy="13" r="10" fill="none" stroke="currentColor" strokeWidth="2.4" />
            <circle cx="13" cy="13" r="4.2" fill="var(--c-primary)" />
            <path d="M3 13h20" stroke="currentColor" strokeWidth="2.4" />
          </svg>
          Overwatch
        </div>
        {service ? <span className={styles.chip}>{service} · invited by your shift lead</span> : null}
        {!submitted ? (
          <>
            <span className={styles.saved} role="status">
              {savedNote ?? ''}
            </span>
            <Link href={REGISTER_LATER_HREF} className={styles.later} data-el="REG-SAVE-LATER-BTN">
              Save and come back later
            </Link>
          </>
        ) : null}
      </header>
      <main className={styles.main}>
        <StageGrid stage={clamped} templates={TEMPLATES} gaps={GAPS} className={styles.grid}>
          <StageArea name="list">
            {submitted ? null : (
              <div className={styles.list}>
                <RegistrationChecklist registrationId={registrationId} stage={clamped} states={states} />
              </div>
            )}
          </StageArea>
          <StageArea name="stage">
            <StageLayer index={clamped} current={clamped}>
              <section aria-label="Current step" className={styles.step}>
                {children}
              </section>
            </StageLayer>
          </StageArea>
          <StageArea name="side">
            {clamped >= 1 && clamped <= 4 ? (
              <StageLayer index={clamped} current={clamped} variant="side">
                <aside aria-label="Help" className={styles.help}>
                  <StepHelp step={clamped} />
                </aside>
              </StageLayer>
            ) : null}
          </StageArea>
        </StageGrid>
      </main>
    </div>
  );
}
