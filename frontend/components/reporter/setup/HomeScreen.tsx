'use client';

import { useRouter } from 'next/navigation';
import { useState, useSyncExternalStore } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { bffRequest } from '@/lib/reporter/browser';
import styles from './Setup.module.css';

// Step 3 of 5 (W34): add DIUCS to the home screen. Notifications only work from the home screen, so
// a reporter who is already in the installed app is carried straight on.

type Platform = 'iPhone' | 'Android';

const IPHONE_STEPS = [
  'Tap Share',
  'Tap Add to Home Screen',
  'Tap Add',
  'Open DIUCS from the home screen',
];
const ANDROID_STEPS = [
  'Open the browser menu',
  'Tap Install app or Add to Home screen',
  'Open DIUCS from the home screen',
];

const IPHONE = /iPhone|iPad|iPod/;

function platformFromAgent(agent: string): Platform {
  return IPHONE.test(agent) ? 'iPhone' : 'Android';
}

function isInstalled(): boolean {
  if (typeof window === 'undefined') return false;
  const nav = navigator as Navigator & { standalone?: boolean };
  if (nav.standalone === true) return true;
  return typeof window.matchMedia === 'function' && window.matchMedia('(display-mode: standalone)').matches;
}

const noListeners = () => () => undefined;

export function HomeScreen() {
  const router = useRouter();
  const [platform, setPlatform] = useState<Platform>(() => platformFromAgent(navigator.userAgent));
  const [notInstalled, setNotInstalled] = useState(false);
  const installed = useSyncExternalStore(noListeners, isInstalled, () => false);

  const added = () => {
    if (isInstalled()) {
      router.push('/setup/notifications');
      return;
    }
    setNotInstalled(true);
  };

  const chooseText = async () => {
    const reply = await bffRequest('/api/bff/reporter/channel', { method: 'POST', body: { channel: 'text' } });
    if (reply.status === 200 || reply.status === 204) router.push('/setup/done?channel=text');
  };

  if (installed) {
    return (
      <main className={styles.page}>
        <h1 className={styles.title}>Welcome. Your set-up continues here.</h1>
        <Button variant="primary" dataEl="ONB-HOME-CONTINUE-BTN" onClick={() => router.push('/setup/notifications')}>
          Continue
        </Button>
      </main>
    );
  }

  const steps = platform === 'iPhone' ? IPHONE_STEPS : ANDROID_STEPS;
  return (
    <main className={styles.page}>
      <p className={styles.caption}>Step 3 of 5</p>
      <h1 className={styles.title}>Add DIUCS to your home screen</h1>
      <div role="tablist" aria-label="Phone">
        {(['iPhone', 'Android'] as const).map((name) => (
          <button
            key={name}
            type="button"
            role="tab"
            aria-selected={platform === name}
            className={styles.option}
            onClick={() => setPlatform(name)}
          >
            {name}
          </button>
        ))}
      </div>
      {platform === 'iPhone' ? <p>iPhone needs iOS 16.4 or later.</p> : null}
      <ol className={styles.steps}>
        {steps.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
      <p>Carry on there. Notifications only work from the home screen.</p>
      {notInstalled ? (
        <Banner
          tone="warning"
          title="Open DIUCS from your home screen to carry on. Notifications only work from there."
        />
      ) : null}
      <Button variant="primary" dataEl="ONB-HOME-ADDED-BTN" onClick={added}>
        I have added it
      </Button>
      <Button variant="neutral" dataEl="ONB-HOME-USETEXT-BTN" onClick={chooseText}>
        I cannot do this. Use text instead
      </Button>
    </main>
  );
}
