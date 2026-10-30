'use client';

import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { OptionButton } from '@/components/ui/OptionButton';
import { bffRequest } from '@/lib/bff/browser';
import styles from '@/components/exec/Exec.module.css';

// On duty (W44, ClinicalAdvisor screen 2): available, busy or away. Away says what happens to unfinished
// requests before it is saved.

type Presence = 'available' | 'busy' | 'away';
const CHOICES: readonly { value: Presence; label: string }[] = [
  { value: 'available', label: 'Available' },
  { value: 'busy', label: 'Busy' },
  { value: 'away', label: 'Away' },
];

export function DutyForm({ available, waiting }: { available: number; waiting: number }) {
  const router = useRouter();
  const [presence, setPresence] = useState<Presence | null>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    if (presence === null) return;
    setBusy(true);
    setError(null);
    const result = await bffRequest<{ presence: string }>('/api/bff/clinical/presence', { method: 'PUT', body: { presence } });
    setBusy(false);
    if (!result.ok) {
      setSaved(false);
      setError('Could not save your status. Try again.');
      return;
    }
    setSaved(true);
    router.refresh();
  };

  return (
    <div className={styles.stack}>
      <h1 className={styles.heading}>Are you taking requests?</h1>
      <div className={styles.group} role="group" aria-label="Your status">
        {CHOICES.map((choice) => (
          <OptionButton
            key={choice.value}
            selected={presence === choice.value}
            onSelect={() => {
              setPresence(choice.value);
              setSaved(false);
            }}
            dataEl={`CLIN-DUTY-${choice.value.toUpperCase()}`}
          >
            {choice.label}
          </OptionButton>
        ))}
      </div>
      {presence === 'away' ? (
        <Banner tone="warning" title="Your unfinished requests go back to the queue." />
      ) : null}
      <div className={styles.actions}>
        <Button variant="primary" busy={busy} disabled={presence === null} onClick={save} dataEl="CLIN-DUTY-SAVE-BTN">
          Save status
        </Button>
      </div>
      {saved ? <p role="status">Status saved.</p> : null}
      {error ? <p role="alert" className={styles.error}>{error}</p> : null}
      <p>{`${waiting} request${waiting === 1 ? '' : 's'} waiting`}</p>
      <p>{`${available} clinical advisor${available === 1 ? '' : 's'} available now`}</p>
      <p className={styles.footer}>Advisors see how many of you are available. They see your name only after you take a request.</p>
    </div>
  );
}
