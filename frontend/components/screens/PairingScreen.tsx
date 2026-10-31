'use client';

import { useRouter } from 'next/navigation';
import { Banner } from '@/components/ui';
import { pollPairing, renewSession, startPairing } from '@/lib/screens/client';
import { usePairing, type PairingApi } from '@/lib/screens/usePairing';
import styles from './PairingScreen.module.css';

const SCREEN_API: PairingApi = { renew: renewSession, start: startPairing, poll: pollPairing };
const BOARD = '/screen';

// What a wall display shows while it waits to be connected (ScreenPairing artboard, step 1). The code
// is the only thing in it that changes. It is kept out of the title, the address and every store.
export function PairingScreen({ api = SCREEN_API }: { api?: PairingApi }) {
  const router = useRouter();
  const view = usePairing({ api, onPaired: () => router.replace(BOARD) });

  return (
    <main className={styles.page}>
      <h1 className={styles.title}>DIUCS capacity wall screen</h1>
      <div className={styles.stage}>
        {view.disconnected === true ? (
          <div className={styles.message}>
            <Banner tone="warning" title="This screen was disconnected." dataEl="WALL-PAIR-DISCONNECTED">
              Ask a shift lead to connect it again with the code below.
            </Banner>
          </div>
        ) : null}
        <div aria-live="polite" className={styles.stage}>
          {view.kind === 'code' ? (
            <>
              <p className={styles.code} data-el="WALL-PAIR-CODE">
                {view.code}
              </p>
              <p className={styles.instruction}>Enter this code in the admin page to connect this screen.</p>
              <p className={styles.waiting}>Waiting to be connected · code works for 10 minutes</p>
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
      </div>
      <p className={styles.footer}>No patient information on this screen</p>
    </main>
  );
}
