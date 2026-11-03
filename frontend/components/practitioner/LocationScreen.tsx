'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { OptionButton } from '@/components/ui/OptionButton';
import { parseSettings, parseShift, type Location } from '@/lib/practitioner/answers';
import { useBffRead } from '@/lib/practitioner/browser';
import { bffRequest } from '@/lib/reporter/browser';
import { PhoneFailed, PhoneOpening, PhoneScreen } from './PhoneScreen';
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

  if (read.kind === 'failed') return <PhoneFailed title="Location" backHref="/app/practitioner">We could not load your choice. Try again shortly.</PhoneFailed>;
  if (read.kind !== 'ready') return <PhoneOpening title="Location" backHref="/app/practitioner" label="Opening your choice." />;
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
          Save my choice
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
      <div className={styles.card} data-el="PRAC-LOCATION-PROMISES">
        <ul className={styles.lines}>
          <li>The coordinator sees your estimated arrival, not a trail.</li>
          <li>It stops when you arrive.</li>
          <li>It is not used to time or rank you.</li>
        </ul>
      </div>
      {/* There is no settings page for this: the choice is made, and changed, here (brief gap 4). */}
      <p className={styles.note}>You can change this at any time on this screen.</p>
      {saved ? (
        <p className={styles.saved} role="status">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
            <path d="M5 12.5l4.5 4.5L19 7.5" />
          </svg>
          <span>Your choice is saved.</span>
        </p>
      ) : null}
      {failed ? <Banner tone="warning" title="We could not save that. Try again." /> : null}
    </PhoneScreen>
  );
}
