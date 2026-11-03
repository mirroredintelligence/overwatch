'use client';

import { useRouter } from 'next/navigation';
import { Banner } from '@/components/ui';
import { pollPairing, renewSession, startPairing } from '@/lib/screens/client';
import { usePairing, type PairingApi } from '@/lib/screens/usePairing';
import styles from './PairingScreen.module.css';

const SCREEN_API: PairingApi = { renew: renewSession, start: startPairing, poll: pollPairing };
const BOARD = '/screen';

// The code is shown as two groups of three; a screen reader gets each digit, in the same two groups.
function spoken(code: string): string {
  return code
    .split(' ')
    .map((group) => group.split('').join(' '))
    .join(', ');
}

const STEPS: readonly { n: number; lead: string; text: string }[] = [
  { n: 1, lead: 'On this screen:', text: 'read the code.' },
  {
    n: 2,
    lead: 'In the admin page:',
    text: 'choose Add a wall screen, enter the code and give the screen a name, for example the room it is in.',
  },
  { n: 3, lead: 'Done:', text: 'this screen shows the live board. It shows capacity only, never patient information.' },
];

// What a wall display shows while it waits to be connected (WallPair artboard). The code, on the left,
// is the only thing in it that changes; the three steps stay on the right. It is kept out of the title,
// the address and every store. The ring is still: the wall plays no motion except on the reconnect view.
export function PairingScreen({ api = SCREEN_API }: { api?: PairingApi }) {
  const router = useRouter();
  const view = usePairing({ api, onPaired: () => router.replace(BOARD) });

  return (
    <main className={styles.page}>
      <section className={styles.code_side}>
        <div className={styles.brand}>
          <svg width="64" height="64" viewBox="0 0 26 26" aria-hidden="true" className={styles.mark}>
            <circle cx="13" cy="13" r="10" fill="none" stroke="currentColor" strokeWidth="2.2" />
            <circle cx="13" cy="13" r="4.2" fill="currentColor" />
            <path d="M3 13h20" stroke="currentColor" strokeWidth="2.2" />
          </svg>
          <div className={styles.name}>Overwatch wall screen</div>
        </div>
        {view.disconnected === true ? (
          <div className={styles.message}>
            <Banner tone="warning" title="This screen was disconnected." dataEl="WALL-PAIR-DISCONNECTED">
              Ask a shift lead to connect it again with the code below.
            </Banner>
          </div>
        ) : null}
        <div aria-live="polite" className={styles.live}>
          {view.kind === 'code' ? (
            <>
              <div>
                <div className={styles.label}>Connect code</div>
                <p className={styles.code} data-el="WALL-PAIR-CODE" role="img" aria-label={spoken(view.code)}>
                  {view.code}
                </p>
              </div>
              <p className={styles.instruction}>Enter this code in the admin page to connect this screen.</p>
              <div className={styles.waiting}>
                <svg width="64" height="64" viewBox="0 0 64 64" aria-hidden="true" className={styles.ring}>
                  <circle cx="32" cy="32" r="26" fill="none" stroke="rgba(255,255,255,.25)" strokeWidth="7" />
                  <circle
                    cx="32"
                    cy="32"
                    r="26"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="7"
                    strokeDasharray="130 164"
                    strokeLinecap="round"
                    transform="rotate(-90 32 32)"
                  />
                </svg>
                <span>Waiting to be connected. The code works for 10 minutes, then this screen shows a new one.</span>
              </div>
            </>
          ) : null}
          {view.kind === 'connecting' ? <p className={styles.instruction}>Connecting this screen…</p> : null}
        </div>
        {view.kind === 'throttled' ? (
          <div className={styles.message}>
            <Banner tone="warning" title="Too many attempts. Wait a few minutes and try again." dataEl="WALL-PAIR-MESSAGE" />
          </div>
        ) : null}
        {view.kind === 'unavailable' ? (
          <div className={styles.message}>
            <Banner tone="warning" title="Pairing is not available right now. Try again shortly." dataEl="WALL-PAIR-MESSAGE" />
          </div>
        ) : null}
      </section>
      <section className={styles.steps_side}>
        <h1 className={styles.heading}>Set up in three steps</h1>
        <ol className={styles.steps}>
          {STEPS.map((step) => (
            <li key={step.n} className={styles.step}>
              <span className={styles.num} aria-hidden="true">
                {step.n}
              </span>
              <span>
                <strong>{step.lead}</strong> {step.text}
              </span>
            </li>
          ))}
        </ol>
        <p className={styles.note}>If it goes offline later, the board keeps showing the last known figures and says so.</p>
      </section>
    </main>
  );
}
