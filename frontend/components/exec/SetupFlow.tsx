'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { AlertSwitches } from '@/components/exec/AlertSwitches';
import { EscalationForm, type EscalationValues } from '@/components/exec/EscalationForm';
import { Button } from '@/components/ui/Button';
import { type AlertPreferences } from '@/lib/exec/alertPrefs';
import { DEPUTY_REQUIRED, hasDeputy, SAVE_FAILED, savePreferences } from '@/lib/exec/savePreferences';
import styles from './Exec.module.css';

// The executive's set-up after verification (W39): the welcome, the alerts, then escalation. The alerts
// step holds its choice; the one save is at the end, because the back end takes the whole state and
// refuses an alert without a deputy. Saving lands on the executive home; the home-screen step (W34) is
// not built yet, so there is no step after this one.

type Step = 'welcome' | 'alerts' | 'escalation';

export function SetupFlow({ initial }: { initial: AlertPreferences }) {
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
    router.push('/planning');
  };

  if (step === 'welcome') {
    return (
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
  }

  if (step === 'alerts') {
    return (
      <section className={styles.section} aria-labelledby="exec-alerts-heading">
        <h1 id="exec-alerts-heading" className={styles.heading}>Choose my alerts</h1>
        <AlertSwitches prefs={prefs} onChange={(next) => setPrefs((current) => ({ ...current, ...next }))} />
        <div className={styles.actions}>
          <Button variant="primary" onClick={() => setStep('escalation')} dataEl="EXEC-ALERTS-SAVE-BTN">
            Save my alerts
          </Button>
        </div>
      </section>
    );
  }

  return (
    <section className={styles.section} aria-labelledby="exec-escalation-heading">
      <h1 id="exec-escalation-heading" className={styles.heading}>If nobody acknowledges</h1>
      <EscalationForm initial={prefs} busy={busy} onSave={saveEscalation} error={error} />
    </section>
  );
}
