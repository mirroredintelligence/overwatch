'use client';

import Link from 'next/link';
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { Button } from '@/components/ui/Button';
import { tenantStore } from '@/lib/storage/tenantStore';
import {
  FIRST_WEEK,
  FIRST_WEEK_NOTE,
  HOW_IT_WORKS,
  ROLE_CHOICES,
  ROLE_SCREENS,
  TOUR_ROLES,
  type TourRole,
} from '@/lib/tour/content';
import styles from './Tour.module.css';

// The one-minute product tour (W52). The steps are in the query string (?step=), and the last step
// and the chosen role are remembered in browser storage when the browser allows it. The practice step
// sends nothing and makes no request: its answers only change what the screen says.

export type TourStep = 'welcome' | 'role' | 'changes' | 'how' | 'practice' | 'week';
const STEPS: readonly TourStep[] = ['welcome', 'role', 'changes', 'how', 'practice', 'week'];
const STEP_NAMES: Record<TourStep, string> = {
  welcome: 'Welcome',
  role: 'Your role',
  changes: 'What changes for you',
  how: 'How it works',
  practice: 'Try it',
  week: 'Your first week',
};
const STORAGE_NAME = 'tour.state';

type Stored = { step?: TourStep; role?: TourRole };

const isStored = (value: unknown): value is Stored =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

// Kept through the one browser-storage helper (TEN-050): per host, interface state only, wiped on
// sign-out. Storage can be blocked: the tour still works; it just does not remember the step.
function readStored(): Stored {
  return tenantStore.get(STORAGE_NAME, isStored) ?? {};
}

function writeStored(value: Stored): void {
  tenantStore.set(STORAGE_NAME, value);
}

// The stored step is read through the store hook, so the server's answer (none) and the browser's
// answer never disagree during hydration. Nothing stored means no resume offer.
function subscribeNothing(): () => void {
  return () => undefined;
}

function readStoredStep(): TourStep | null {
  const step = readStored().step;
  return step !== undefined && STEPS.includes(step) ? step : null;
}

export function Tour({ initialStep, initialRole }: { initialStep: TourStep; initialRole?: TourRole }) {
  const [step, setStep] = useState<TourStep>(initialStep);
  const [role, setRole] = useState<TourRole | null>(initialRole ?? null);
  const [practiceDone, setPracticeDone] = useState(false);
  const storedStep = useSyncExternalStore(subscribeNothing, readStoredStep, () => null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const first = useRef(true);

  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    headingRef.current?.focus();
  }, [step]);

  function go(next: TourStep) {
    setStep(next);
    writeStored({ step: next, role: role ?? undefined });
    try {
      const url = new URL(window.location.href);
      url.searchParams.set('step', next);
      window.history.replaceState(null, '', url.toString());
    } catch {
      // A page address that cannot be changed still shows the step.
    }
  }

  function chooseRole(next: TourRole) {
    setRole(next);
    writeStored({ step, role: next });
  }

  const index = STEPS.indexOf(step);
  const back = index > 0 ? STEPS[index - 1] : undefined;
  const next = index < STEPS.length - 1 ? STEPS[index + 1] : undefined;
  const screen = role === null ? null : ROLE_SCREENS[role];
  // The reporter's screen leads to the practice step and has no Skip (the product rule for that role).
  const showSkip = !(step === 'changes' && role === 'reporter');

  return (
    <div className={styles.shell}>
      <header className={styles.bar}>
        <div className={styles.brand}>
          <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true" focusable="false">
            <circle cx="13" cy="13" r="10" fill="none" stroke="currentColor" strokeWidth="2.4" />
            <circle cx="13" cy="13" r="4.2" fill="currentColor" />
            <path d="M3 13h20" stroke="currentColor" strokeWidth="2.4" />
          </svg>
          One-minute tour
        </div>
        {showSkip && (
          <Link className={styles.skip} href="/">
            Skip
          </Link>
        )}
      </header>

      <main className={styles.page}>
        <div className={styles.progress}>
          <div className={styles.progressMeta}>
            <span>Step {index + 1} of {STEPS.length}</span>
            <span>{STEP_NAMES[step]}</span>
          </div>
          <div className={styles.segments} aria-hidden="true">
            {STEPS.map((item, i) => (
              <span key={item} className={i <= index ? styles.segmentOn : styles.segment} />
            ))}
          </div>
        </div>

        {step === 'welcome' && (
          <section className={`${styles.card} ${styles.cardDark}`} aria-labelledby="tour-title">
            <h1 id="tour-title" ref={headingRef} tabIndex={-1} className={styles.title}>See how Overwatch works for you</h1>
            <p className={styles.lead}>One minute. No account needed.</p>
            <div className={styles.actions}>
              {storedStep !== null && storedStep !== 'welcome' && (
                <Button variant="secondary" onClick={() => go(storedStep)}>Carry on where you left off</Button>
              )}
              <Button variant="primary" onClick={() => go('role')} dataEl="TOUR-START-BTN">Start the tour</Button>
            </div>
          </section>
        )}

        {step === 'role' && (
          <section className={styles.card} aria-labelledby="tour-role">
            <h1 id="tour-role" ref={headingRef} tabIndex={-1} className={styles.title}>Which is you?</h1>
            <p className={styles.lead}>We will show what changes for your role.</p>
            <fieldset className={styles.options} aria-labelledby="tour-role">
              {TOUR_ROLES.map((item) => (
                <label key={item} className={styles.choice} data-checked={role === item ? 'true' : undefined}>
                  <input
                    type="radio"
                    name="tour-role"
                    className={styles.radio}
                    value={item}
                    checked={role === item}
                    onChange={() => chooseRole(item)}
                    data-el={`TOUR-ROLE-${item.toUpperCase()}`}
                  />
                  <span className={styles.dot} aria-hidden="true" />
                  <span>{ROLE_CHOICES[item]}</span>
                </label>
              ))}
            </fieldset>
          </section>
        )}

        {step === 'changes' && screen !== null && role !== null && (
          <section className={styles.card} aria-labelledby="tour-changes">
            <h1 id="tour-changes" ref={headingRef} tabIndex={-1} className={styles.title}>{screen.heading}</h1>
            <h2 className={styles.sub}>Today</h2>
            <ul aria-label="Today" className={styles.list}>
              {screen.today.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
            <h2 className={styles.sub}>With Overwatch</h2>
            <ul aria-label="With Overwatch" className={styles.list}>
              {screen.withOverwatch.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
            {screen.closing !== undefined && <p className={styles.lead}>{screen.closing}</p>}
            <div className={styles.actions}>
              {role === 'reporter' || role === 'advisor' ? (
                <Button variant="secondary" onClick={() => go('practice')}>{screen.action}</Button>
              ) : (
                <Button variant="secondary" href={screen.actionHref ?? '/'} dataEl="TOUR-ROLE-ACTION-BTN">{screen.action}</Button>
              )}
            </div>
          </section>
        )}
        {step === 'changes' && role === null && <p role="alert" className={styles.lead}>Choose your role first.</p>}

        {step === 'how' && (
          <section className={styles.card} aria-labelledby="tour-how">
            <h1 id="tour-how" ref={headingRef} tabIndex={-1} className={styles.title}>How it works</h1>
            <ol aria-label="How it works" className={styles.steps}>
              {HOW_IT_WORKS.map((item, i) => (
                <li key={item.title} className={styles.howStep}>
                  <span className={styles.number} aria-hidden="true">{i + 1}</span>
                  <span>
                    <strong>{item.title}</strong>
                    <span className={styles.lead}>{item.body}</span>
                  </span>
                </li>
              ))}
            </ol>
            <p className={styles.lead}>We never send or ask for patient information.</p>
          </section>
        )}

        {step === 'practice' && (
          <section className={styles.card} aria-labelledby="tour-practice">
            <p className={styles.label}>Sample data</p>
            <h1 id="tour-practice" ref={headingRef} tabIndex={-1} className={styles.title}>Answer a practice prompt</h1>
            <p>We have 3 referrals in the next 2 hours. Still right?</p>
            {practiceDone ? (
              <p role="status" className={styles.lead}>Practice done</p>
            ) : (
              <div className={styles.pair}>
                <Button variant="primary" onClick={() => setPracticeDone(true)} dataEl="TOUR-PRACTICE-YES-BTN">Yes, still right</Button>
                <Button variant="secondary" onClick={() => setPracticeDone(true)}>Send a new number</Button>
              </div>
            )}
            <p className={styles.label}>Nothing is sent. Your answer only changes what the screen says.</p>
          </section>
        )}

        {step === 'week' && (
          <section className={styles.card} aria-labelledby="tour-week">
            <h1 id="tour-week" ref={headingRef} tabIndex={-1} className={styles.title}>Your first week</h1>
            <ul className={styles.checks}>
              {FIRST_WEEK.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
            <p className={styles.lead}>{FIRST_WEEK_NOTE}</p>
            <div className={styles.actions}>
              <Button variant="primary" href="/">Go to my app</Button>
            </div>
            <Link className={styles.again} href="/tour?step=welcome">Start again</Link>
          </section>
        )}

        {step !== 'welcome' && (
          <nav aria-label="Tour steps" className={styles.nav}>
            {back !== undefined && <Button variant="neutral" onClick={() => go(back)}>Back</Button>}
            {next !== undefined && (
              <Button
                variant="primary"
                disabled={step === 'role' && role === null}
                onClick={() => go(next)}
                dataEl="TOUR-NEXT-BTN"
              >
                Next
              </Button>
            )}
          </nav>
        )}
      </main>
    </div>
  );
}
