'use client';

import { useId } from 'react';
import { OptionButton } from '@/components/ui/OptionButton';
import { NOT_UPDATED_CHOICES, type AlertKind, type AlertPreferences } from '@/lib/exec/alertPrefs';
import styles from './Exec.module.css';

// The six alert switches on the set-up and settings screens (W39, ExecApp2 screen 2). Each is a real
// switch (role "switch", aria-checked), toggled by Space or Enter, with its title as its name.

type Props = {
  prefs: AlertPreferences;
  onChange: (next: Partial<AlertPreferences>) => void;
};

const KIND_TEXT: Record<AlertKind, { title: string; hint: string }> = {
  'service-closed': { title: 'A service closes unexpectedly', hint: 'Not planned out-of-hours closures' },
  'over-capacity': { title: 'A service goes over capacity', hint: 'When it moves past its established level' },
  'not-updated': { title: 'A service has not updated', hint: 'After 2 hrs. Choose 2 or 4 hrs.' },
  'system-pressure': { title: 'System pressure rises', hint: 'When 5 or more services are limited or worse' },
};

const DATA_EL: Record<AlertKind, string> = {
  'service-closed': 'EXEC-ALERT-SERVICE-CLOSED-SWITCH',
  'over-capacity': 'EXEC-ALERT-OVER-CAPACITY-SWITCH',
  'not-updated': 'EXEC-ALERT-NOT-UPDATED-SWITCH',
  'system-pressure': 'EXEC-ALERT-SYSTEM-PRESSURE-SWITCH',
};

function Switch({ on, title, hint, dataEl, onToggle }: { on: boolean; title: string; hint: string; dataEl: string; onToggle: () => void }) {
  const titleId = useId();
  const hintId = useId();
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-labelledby={titleId}
      aria-describedby={hintId}
      className={styles.switchRow}
      onClick={onToggle}
      data-el={dataEl}
    >
      <span className={styles.switchText}>
        <span id={titleId} className={styles.switchTitle}>{title}</span>
        <span id={hintId} className={styles.switchHint}>{hint}</span>
      </span>
      <span className={styles.track} aria-hidden="true">
        <span className={styles.knob} />
      </span>
    </button>
  );
}

export function AlertSwitches({ prefs, onChange }: Props) {
  const toggleKind = (kind: AlertKind) => {
    const on = prefs.kinds.includes(kind);
    onChange({ kinds: on ? prefs.kinds.filter((k) => k !== kind) : [...prefs.kinds, kind] });
  };
  const notUpdatedOn = prefs.kinds.includes('not-updated');

  return (
    <div className={styles.stack}>
      {(Object.keys(KIND_TEXT) as AlertKind[]).map((kind) => {
        const text = KIND_TEXT[kind];
        const hint = kind === 'not-updated' ? `After ${prefs.notUpdatedHours} hrs. Choose 2 or 4 hrs.` : text.hint;
        return (
          <div key={kind}>
            <Switch
              on={prefs.kinds.includes(kind)}
              title={text.title}
              hint={hint}
              dataEl={DATA_EL[kind]}
              onToggle={() => toggleKind(kind)}
            />
            {kind === 'not-updated' && notUpdatedOn ? (
              <fieldset className={styles.group}>
                <legend className={styles.legend}>Not updated for</legend>
                {NOT_UPDATED_CHOICES.map((hours) => (
                  <OptionButton
                    key={hours}
                    selected={prefs.notUpdatedHours === hours}
                    onSelect={() => onChange({ notUpdatedHours: hours })}
                    dataEl={`EXEC-ALERT-NOTUPDATED-${hours}`}
                  >
                    {`${hours} hrs`}
                  </OptionButton>
                ))}
              </fieldset>
            ) : null}
          </div>
        );
      })}
      <Switch
        on={prefs.dailySummary}
        title="Daily summary"
        hint="07:30, by notification"
        dataEl="EXEC-ALERT-DAILY-SWITCH"
        onToggle={() => onChange({ dailySummary: !prefs.dailySummary })}
      />
      <Switch
        on={prefs.weeklySummary}
        title="Weekly summary"
        hint="Mondays, by email"
        dataEl="EXEC-ALERT-WEEKLY-SWITCH"
        onToggle={() => onChange({ weeklySummary: !prefs.weeklySummary })}
      />
      <p className={styles.footer}>Alerts never include patient information. You can change these at any time.</p>
    </div>
  );
}
