'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { OptionButton } from '@/components/ui/OptionButton';
import { parseSettings, parseShift, type Location } from '@/lib/practitioner/answers';
import { useBffRead } from '@/lib/practitioner/browser';
import { bffRequest } from '@/lib/reporter/browser';
import { PhoneScreen } from './PhoneScreen';
import styles from './practitioner.module.css';

// Location sharing (RadarPhone 4): only while travelling to a visit, or never. What is shared is an
// estimated arrival the person gives for a visit, never a trail and never a position; it stops on arrival
// and is not used to time or rank anyone. The choice starts as "never", so nothing is shared until the
// person turns it on.

export function LocationScreen() {
  const router = useRouter();
  const read = useBffRead('/api/bff/practitioner/shift', parseShift);
  // What the person has picked on this screen; until they pick, what the back end holds.
  const [picked, setPicked] = useState<Location | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (read.kind === 'ended') router.replace('/app/pin');
  }, [read, router]);

  if (read.kind === 'failed') return <PhoneScreen title="Location" backHref="/app/practitioner"><p>We could not load your choice. Try again shortly.</p></PhoneScreen>;
  if (read.kind !== 'ready') return <PhoneScreen title="Location" backHref="/app/practitioner"><p role="status">Opening your choice</p></PhoneScreen>;
  const choice = picked ?? read.value.location;

  const save = async () => {
    if (busy) return;
    setBusy(true);
    setFailed(false);
    setSaved(false);
    const reply = await bffRequest('/api/bff/practitioner/settings', { method: 'PUT', body: { location: choice } });
    setBusy(false);
    if (reply.status === 401) return router.replace('/app/pin');
    const answer = reply.status === 200 ? parseSettings(reply.body) : null;
    if (answer === null) return setFailed(true);
    setPicked(answer.location);
    return setSaved(true);
  };

  return (
    <PhoneScreen
      title="Location"
      backHref="/app/practitioner"
      actions={
        <Button variant="primary" busy={busy} dataEl="PRAC-LOCATION-SAVE-BTN" onClick={() => void save()}>
          Save choice
        </Button>
      }
    >
      <h1 className={styles.title}>Share your location on visits?</h1>
      <div className={styles.group} role="group" aria-label="Share your location on visits">
        <OptionButton selected={choice === 'travel'} onSelect={() => setPicked('travel')} dataEl="PRAC-LOCATION-TRAVEL">
          Only while I travel to a visit
        </OptionButton>
        <OptionButton selected={choice === 'never'} onSelect={() => setPicked('never')} dataEl="PRAC-LOCATION-NEVER">
          Never
        </OptionButton>
      </div>
      <div className={styles.panel} data-el="PRAC-LOCATION-PROMISES">
        <ul className={styles.lines}>
          <li>The coordinator sees your estimated arrival, not a trail.</li>
          <li>It stops when you arrive.</li>
          <li>It is not used to time or rank you.</li>
        </ul>
      </div>
      <p className={styles.note}>You can change this at any time in Settings.</p>
      {saved ? <p role="status">Your choice is saved.</p> : null}
      {failed ? <Banner tone="warning" title="We could not save that. Try again." /> : null}
    </PhoneScreen>
  );
}
