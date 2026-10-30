'use client';

import { useState } from 'react';
import { AlertSwitches } from '@/components/exec/AlertSwitches';
import { EscalationForm, type EscalationValues } from '@/components/exec/EscalationForm';
import { Button } from '@/components/ui/Button';
import { Banner } from '@/components/ui/Banner';
import { type AlertPreferences } from '@/lib/exec/alertPrefs';
import type { Leader } from '@/lib/exec/leaders';
import { DEPUTY_REQUIRED, hasDeputy, SAVE_FAILED, savePreferences } from '@/lib/exec/savePreferences';
import styles from './Exec.module.css';

// Alerts and escalation together (W39, the settings screen). Each save sends the whole state, because
// the back end keeps one subscription per practitioner.

export function SettingsForm({ initial, leaders }: { initial: AlertPreferences; leaders?: Leader[] | null }) {
  const [prefs, setPrefs] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const save = async (next: AlertPreferences) => {
    if (!hasDeputy(next)) {
      setSaved(false);
      setError(DEPUTY_REQUIRED);
      return;
    }
    setBusy(true);
    setError(null);
    const result = await savePreferences(next);
    setBusy(false);
    if (!result.ok) {
      setSaved(false);
      setError(SAVE_FAILED);
      return;
    }
    setPrefs(result.data);
    setSaved(true);
  };

  const saveEscalation = (values: EscalationValues) => save({ ...prefs, ...values });

  return (
    <div className={styles.stack}>
      <section className={styles.section} aria-labelledby="settings-alerts-heading">
        <h2 id="settings-alerts-heading" className={styles.heading}>Choose my alerts</h2>
        <AlertSwitches prefs={prefs} onChange={(next) => setPrefs((current) => ({ ...current, ...next }))} />
        <div className={styles.actions}>
          <Button variant="primary" busy={busy} onClick={() => save(prefs)} dataEl="EXEC-ALERTS-SAVE-BTN">
            Save my alerts
          </Button>
        </div>
      </section>
      <section className={styles.section} aria-labelledby="settings-escalation-heading">
        <h2 id="settings-escalation-heading" className={styles.heading}>If nobody acknowledges</h2>
        <EscalationForm initial={prefs} busy={busy} onSave={saveEscalation} error={error} leaders={leaders} />
      </section>
      {saved ? <Banner tone="info" title="Your choices are saved." dataEl="EXEC-SETTINGS-SAVED" /> : null}
    </div>
  );
}
