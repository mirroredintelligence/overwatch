'use client';

import { useState } from 'react';
import { Disclose } from '@/components/admin/Disclose';
import { AlertSwitches } from '@/components/exec/AlertSwitches';
import { EscalationForm } from '@/components/exec/EscalationForm';
import { Button } from '@/components/ui/Button';
import { Banner } from '@/components/ui/Banner';
import { type AlertPreferences, QUIET_END, QUIET_START } from '@/lib/exec/alertPrefs';
import type { Leader } from '@/lib/exec/leaders';
import { DEPUTY_REQUIRED, hasDeputy, SAVE_FAILED, savePreferences } from '@/lib/exec/savePreferences';
import styles from './Settings.module.css';

// Alerts and escalation together (W39, PSettings). The six switches sit on one card; quiet hours and the
// deputy sit in a disclosure whose line says what is set. There is one save, at the foot of the page, and it
// sends the whole state, because the back end keeps one subscription per practitioner.

type Props = {
  initial: AlertPreferences;
  leaders?: Leader[] | null;
};

/** The disclosure's answer in one line, read from the state. */
function escalationLine(prefs: AlertPreferences): string {
  const quiet = prefs.quietHours === null
    ? 'No quiet hours'
    : `Quiet ${QUIET_START} to ${QUIET_END}, ${prefs.quietCriticalOnly ? 'critical only' : 'everything'}`;
  const deputy = prefs.deputy === '' ? 'No deputy chosen yet' : `Deputy alerted after ${prefs.ackMinutes} min`;
  return `${quiet}. ${deputy}.`;
}

export function SettingsForm({ initial, leaders }: Props) {
  const [prefs, setPrefs] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [escalationOpen, setEscalationOpen] = useState(false);

  // A deputy must be someone on the list when there is a list: a saved deputy who has since left it is refused.
  const deputyChosen = (next: AlertPreferences) =>
    hasDeputy(next) && (!Array.isArray(leaders) || leaders.some((leader) => leader.id === next.deputy));

  const save = async (next: AlertPreferences) => {
    if (!deputyChosen(next)) {
      setSaved(false);
      setError(DEPUTY_REQUIRED);
      setEscalationOpen(true);
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

  return (
    <div className={styles.page}>
      <AlertSwitches prefs={prefs} onChange={(next) => setPrefs((current) => ({ ...current, ...next }))} />
      <Disclose
        open={escalationOpen}
        onToggle={() => setEscalationOpen((open) => !open)}
        title="Quiet hours and escalation"
        hint={escalationLine(prefs)}
      >
        <EscalationForm
          initial={prefs}
          busy={busy}
          onSave={(values) => save({ ...prefs, ...values })}
          onChange={(values) => setPrefs((current) => ({ ...current, ...values }))}
          leaders={leaders}
          showSave={false}
        />
      </Disclose>
      <div className={styles.saveRow}>
        <Button variant="primary" busy={busy} onClick={() => save(prefs)} dataEl="EXEC-ALERTS-SAVE-BTN">
          Save my alerts
        </Button>
        <p className={styles.hint}>Saved changes apply from the next alert.</p>
      </div>
      {error ? <p className={styles.error} role="alert">{error}</p> : null}
      {saved ? <Banner tone="info" title="Your choices are saved." dataEl="EXEC-SETTINGS-SAVED" /> : null}
    </div>
  );
}
