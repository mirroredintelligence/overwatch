'use client';

import { useRouter } from 'next/navigation';
import { useState, type ReactNode } from 'react';
import { AlertSwitches } from '@/components/exec/AlertSwitches';
import { EscalationForm, type EscalationValues } from '@/components/exec/EscalationForm';
import { Button } from '@/components/ui/Button';
import { type AlertPreferences } from '@/lib/exec/alertPrefs';
import type { Leader } from '@/lib/exec/leaders';
import { DEPUTY_REQUIRED, hasDeputy, SAVE_FAILED, savePreferences } from '@/lib/exec/savePreferences';
import styles from './Exec.module.css';
import settings from './Settings.module.css';

// The executive's set-up after verification (W39): the welcome, the alerts, then escalation. The alerts
// step holds its choice; the one save is at the end, because the back end takes the whole state and
// refuses an alert without a deputy. Saving goes where the page says: an executive goes on to switch on
// alerts on their phone (W9H, DEC-1040), a lead to the home screen. A stepper beside the step shows where
// the person is (PSettings).

type Step = 'welcome' | 'alerts' | 'escalation';

const STEPS: readonly { step: Step; label: string }[] = [
  { step: 'welcome', label: 'Welcome' },
  { step: 'alerts', label: 'Choose your alerts' },
  { step: 'escalation', label: 'Quiet hours and escalation' },
];

export function SetupFlow({ initial, leaders, next: after = '/planning' }: { initial: AlertPreferences; leaders?: Leader[] | null; next?: string }) {
  const router = useRouter();
  const [step, setStep] = useState<Step>('welcome');
  const [prefs, setPrefs] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const saveEscalation = async (values: EscalationValues) => {
    const next = { ...prefs, ...values };
    if (!hasDeputy(next)) {
      setError(DEPUTY_REQUIRED);
      return;
    }
    setBusy(true);
    setError(null);
    const result = await savePreferences(next);
    setBusy(false);
    if (!result.ok) {
      setError(SAVE_FAILED);
      return;
    }
    router.push(after);
  };

  const current = STEPS.findIndex((item) => item.step === step);

  let body: ReactNode;
  if (step === 'welcome') {
    body = (
      <section className={styles.section} aria-labelledby="exec-welcome-heading">
        <h1 id="exec-welcome-heading" className={styles.heading}>The whole system in your pocket</h1>
        <p>See what is open, what is under pressure, and get an alert only when it matters.</p>
        <ul>
          <li>Fewer status calls and catch-up meetings</li>
          <li>Pressure seen as it builds, not at the next meeting</li>
          <li>No patient information, ever</li>
        </ul>
        <div className={styles.actions}>
          <Button variant="primary" onClick={() => setStep('alerts')} dataEl="EXEC-WELCOME-CHOOSE-BTN">
            Choose my alerts
          </Button>
        </div>
      </section>
    );
  } else if (step === 'alerts') {
    body = (
      <section className={styles.section} aria-labelledby="exec-alerts-heading">
        <h1 id="exec-alerts-heading" className={styles.heading}>Choose your alerts</h1>
        <AlertSwitches prefs={prefs} onChange={(next) => setPrefs((currentPrefs) => ({ ...currentPrefs, ...next }))} />
        <div className={styles.actions}>
          <Button variant="primary" onClick={() => setStep('escalation')} dataEl="EXEC-ALERTS-SAVE-BTN">
            Save my alerts
          </Button>
        </div>
      </section>
    );
  } else {
    body = (
      <section className={styles.section} aria-labelledby="exec-escalation-heading">
        <h1 id="exec-escalation-heading" className={styles.heading}>If nobody acknowledges</h1>
        <EscalationForm initial={prefs} busy={busy} onSave={saveEscalation} error={error} leaders={leaders} />
      </section>
    );
  }

  return (
    <div className={settings.setup}>
      <ol aria-label="Set-up steps" className={settings.steps}>
        {STEPS.map((item, index) => (
          <li key={item.step} className={settings.step} aria-current={index === current ? 'step' : undefined}>
            <span
              className={settings.mark}
              data-state={index < current ? 'done' : index === current ? 'current' : 'todo'}
              aria-hidden="true"
            >
              {index < current ? '✓' : index + 1}
            </span>
            {index < current ? <span className={settings.srOnly}>Done,</span> : null}
            <span>{item.label}</span>
          </li>
        ))}
      </ol>
      <div>{body}</div>
    </div>
  );
}
