'use client';

import Link from 'next/link';
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { Button } from '@/components/ui/Button';
import { Chip } from '@/components/ui/Chip';
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
// and the chosen role are remembered in localStorage when the browser allows it. The practice step
// sends nothing and makes no request: its answers only change what the screen says.

export type TourStep = 'welcome' | 'role' | 'changes' | 'how' | 'practice' | 'week';
const STEPS: readonly TourStep[] = ['welcome', 'role', 'changes', 'how', 'practice', 'week'];
const STORAGE_KEY = 'diucs-tour';

type Stored = { step?: TourStep; role?: TourRole };

function readStored(): Stored {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Stored;
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

function writeStored(value: Stored): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch {
    // Storage can be blocked. The tour still works; it just does not remember the step.
  }
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

  return (
    <main className={styles.page}>
      {step === 'welcome' && (
        <section aria-labelledby="tour-title">
          <h1 id="tour-title" ref={headingRef} tabIndex={-1} className={styles.title}>Less chasing. Faster answers.</h1>
          <p>DIUCS capacity replaces phone calls, emails and whiteboards with one tap or one text.</p>
          <ul>
            <li>Fewer phone calls</li>
            <li>Fewer catch-up meetings</li>
            <li>Capacity updated in seconds</li>
          </ul>
          {storedStep !== null && storedStep !== 'welcome' && (
            <Button variant="secondary" onClick={() => go(storedStep)}>Carry on where you left off</Button>
          )}
          <Button variant="primary" onClick={() => go('role')} dataEl="TOUR-START-BTN">Take the 1-minute tour</Button>
          <Button variant="neutral" href="/" dataEl="TOUR-SKIP-BTN">Skip for now</Button>
        </section>
      )}

      {step === 'role' && (
        <section aria-labelledby="tour-role">
          <h1 id="tour-role" ref={headingRef} tabIndex={-1} className={styles.title}>What do you do?</h1>
          <div className={styles.options} role="radiogroup" aria-label="What do you do?">
            {TOUR_ROLES.map((item) => (
              <Chip
                key={item}
                pressed={role === item}
                onPressedChange={() => chooseRole(item)}
                dataEl={`TOUR-ROLE-${item.toUpperCase()}`}
              >
                {ROLE_CHOICES[item]}
              </Chip>
            ))}
          </div>
          <p>We show you what changes for your role.</p>
          <Button variant="primary" disabled={role === null} onClick={() => next && go(next)} dataEl="TOUR-NEXT-BTN">
            Continue
          </Button>
        </section>
      )}

      {step === 'changes' && screen !== null && role !== null && (
        <section aria-labelledby="tour-changes">
          <h1 id="tour-changes" ref={headingRef} tabIndex={-1} className={styles.title}>{screen.heading}</h1>
          <h2 className={styles.sub}>Today</h2>
          <ul aria-label="Today">
            {screen.today.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          <h2 className={styles.sub}>With DIUCS</h2>
          <ul aria-label="With DIUCS">
            {screen.withDiucs.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          {screen.closing !== undefined && <p>{screen.closing}</p>}
          {role === 'reporter' || role === 'advisor' ? (
            <Button variant="secondary" onClick={() => go('practice')}>{screen.action}</Button>
          ) : (
            <Button variant="secondary" href="/">{screen.action}</Button>
          )}
          {next && <Button variant="primary" onClick={() => go(next)} dataEl="TOUR-NEXT-BTN">Next</Button>}
        </section>
      )}
      {step === 'changes' && role === null && <p role="alert">Choose your role first.</p>}

      {step === 'how' && (
        <section aria-labelledby="tour-how">
          <h1 id="tour-how" ref={headingRef} tabIndex={-1} className={styles.title}>How it works</h1>
          <ol>
            {HOW_IT_WORKS.map((item) => (
              <li key={item.title}>
                <strong>{item.title}</strong>
                <p>{item.body}</p>
              </li>
            ))}
          </ol>
          <p>We never send or ask for patient information.</p>
          {next && <Button variant="primary" onClick={() => go(next)} dataEl="TOUR-NEXT-BTN">Next</Button>}
        </section>
      )}

      {step === 'practice' && (
        <section aria-labelledby="tour-practice">
          <p className={styles.label}>Sample data</p>
          <h1 id="tour-practice" ref={headingRef} tabIndex={-1} className={styles.title}>Practice update</h1>
          <p className={styles.label}>Practice. Nothing is sent.</p>
          <p>We have 3 referrals in the next 2 hours. Still right?</p>
          {practiceDone ? (
            <p role="status">Practice done</p>
          ) : (
            <div className={styles.options}>
              <Button variant="primary" onClick={() => setPracticeDone(true)} dataEl="TOUR-PRACTICE-YES-BTN">Yes, still 3</Button>
              <Button variant="secondary" onClick={() => setPracticeDone(true)}>Send a new number</Button>
            </div>
          )}
          {next && <Button variant="neutral" onClick={() => go(next)}>Skip practice</Button>}
        </section>
      )}

      {step === 'week' && (
        <section aria-labelledby="tour-week">
          <h1 id="tour-week" ref={headingRef} tabIndex={-1} className={styles.title}>Your first week</h1>
          <ul>
            {FIRST_WEEK.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <p>{FIRST_WEEK_NOTE}</p>
          <Button variant="primary" href="/">Go to my app</Button>
        </section>
      )}

      {back !== undefined && (
        <nav aria-label="Tour steps">
          <Button variant="neutral" onClick={() => go(back)}>Back</Button>
        </nav>
      )}
      {step === 'week' && <Link href="/tour?step=welcome">Start again</Link>}
    </main>
  );
}
