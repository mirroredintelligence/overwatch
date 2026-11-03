'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Loading, Skeleton } from '@/components/ui/Skeleton';
import { bffRequest } from '@/lib/reporter/browser';
import { parseInvitation } from '@/lib/reporter/model';
import styles from './Onboarding.module.css';

// The invitation link's landing (W33): look the token up through the BFF, then go to the set-up
// flow with the token in the address. An expired or used invitation is said plainly; a failed
// check is not called expired, because nobody has checked it. This file also holds the frame the
// set-up pages share (R2 to R4): the dark top bar, the five progress segments and one column.

type State = 'checking' | 'expired' | 'failed';

const STEPS_TOTAL = 5;

/** The top bar, the progress and the column of a set-up page. `step` 0 draws the progress without a name (the welcome). */
export function SetupFrame({
  service,
  step = 0,
  view,
  children,
}: {
  service?: string;
  step?: number;
  view: string;
  children: ReactNode;
}) {
  return (
    <div className={styles.frame}>
      <header className={styles.bar}>
        <span className={styles.brand}>
          <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true" focusable="false">
            <circle cx="13" cy="13" r="10" fill="none" stroke="currentColor" strokeWidth="2.4" />
            <circle cx="13" cy="13" r="4.2" fill="currentColor" />
            <path d="M3 13h20" stroke="currentColor" strokeWidth="2.4" />
          </svg>
          Overwatch
        </span>
        {service === undefined ? null : <span className={styles.service}>{service}</span>}
      </header>
      {view === 'expired' || view === 'failed' || view === 'checking' ? null : (
        <div
          className={styles.progress}
          {...(step > 0 ? { role: 'img', 'aria-label': `Step ${step} of ${STEPS_TOTAL}` } : { 'aria-hidden': true })}
        >
          {Array.from({ length: STEPS_TOTAL }, (_, index) => (
            <span key={index} className={`${styles.seg} ${index < step ? styles.segOn : ''}`} />
          ))}
        </div>
      )}
      <main className={styles.column}>
        <div key={view} className={styles.view}>
          {children}
        </div>
      </main>
    </div>
  );
}

/** The page's one h1: focus lands here on each step, so a screen reader starts at the top of what is new. */
export function StepHeading({ className, children }: { className?: string; children: ReactNode }) {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    ref.current?.focus();
  }, []);
  return (
    <h1 ref={ref} tabIndex={-1} className={className ?? styles.title}>
      {children}
    </h1>
  );
}

/** The loading state: a shimmer in the shape of what is coming, with a spoken label. */
export function SetupLoading({ label }: { label: string }) {
  return (
    <Loading label={label}>
      <div className={styles.shimmer}>
        <Skeleton shape="line" width="40%" />
        <Skeleton shape="title" width="85%" />
        <Skeleton shape="block" />
      </div>
    </Loading>
  );
}

/** Expired, or failed to check: what happened and what to do, in plain words (States board). */
export function InvitationUnusable({ kind }: { kind: 'expired' | 'failed' }) {
  const expired = kind === 'expired';
  return (
    <SetupFrame view={kind}>
      <section className={styles.state}>
        {expired ? (
          <div className={styles.stateIcon} aria-hidden="true">
            ✕
          </div>
        ) : null}
        <StepHeading className={styles.stateTitle}>
          {expired ? 'This invitation has expired' : 'We could not check this invitation'}
        </StepHeading>
        <p className={styles.stateText}>
          {expired
            ? 'Invitations work for 48 hours. Ask your shift lead to send you a new one.'
            : 'We could not check this invitation. Try again shortly.'}
        </p>
      </section>
    </SetupFrame>
  );
}

/** The Expired state for a token that cannot be an invitation: no request is made. */
export function InvitationExpired() {
  return <InvitationUnusable kind="expired" />;
}

export function InvitationLoader({ token }: { token: string }) {
  const router = useRouter();
  const [state, setState] = useState<State>('checking');

  useEffect(() => {
    let live = true;
    void bffRequest(`/api/bff/invitations/${encodeURIComponent(token)}`).then((reply) => {
      if (!live) return;
      // 410 is the back end's one answer for an invitation it will not use; a failed check is not that.
      if (reply.status === 410) return setState('expired');
      const invitation = reply.status === 200 ? parseInvitation(reply.body) : null;
      if (invitation === null) return setState('failed');
      if (invitation.state !== 'valid') return setState('expired');
      router.replace(`/setup?invite=${encodeURIComponent(token)}`);
    });
    return () => {
      live = false;
    };
  }, [token, router]);

  if (state === 'checking') {
    return (
      <SetupFrame view="checking">
        <SetupLoading label="Checking your invitation" />
      </SetupFrame>
    );
  }
  return <InvitationUnusable kind={state} />;
}
