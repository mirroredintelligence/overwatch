'use client';

import { useRouter } from 'next/navigation';
import { useState, useSyncExternalStore } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { recordChannelForDevice } from '@/lib/reporter/channel';
import { StepCards, type StepCard } from '../parts/StepCards';
import styles from './Setup.module.css';

// Step 3 of 5 (W34): add Overwatch to the home screen. Notifications only work from the home screen, so
// a reporter who is already in the installed app is carried straight on.

type Platform = 'iPhone' | 'Android';

// Each step has the line under it that the artboard (OnboardReporter1, "Add to home screen") gives.
const CARRY_ON = 'Carry on there. Notifications only work from the home screen.';
const IPHONE_STEPS: StepCard[] = [
  { key: 'share', title: 'Tap Share', hint: 'The square with an arrow, at the bottom of the screen' },
  { key: 'add-to-home', title: 'Tap Add to Home Screen', hint: 'Scroll down the list if you cannot see it' },
  { key: 'add', title: 'Tap Add', hint: 'The Overwatch icon appears on your home screen' },
  { key: 'open', title: 'Open Overwatch from the home screen', hint: CARRY_ON },
];
const ANDROID_STEPS: StepCard[] = [
  { key: 'menu', title: 'Open the browser menu', hint: 'Usually the three dots at the top of the screen' },
  { key: 'install', title: 'Tap Install app or Add to Home screen', hint: 'Scroll down the menu if you cannot see it' },
  { key: 'open', title: 'Open Overwatch from the home screen', hint: CARRY_ON },
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
  const [textFailed, setTextFailed] = useState(false);
  const installed = useSyncExternalStore(noListeners, isInstalled, () => false);

  const added = () => {
    if (isInstalled()) {
      router.push('/setup/notifications');
      return;
    }
    setNotInstalled(true);
  };

  // No one is signed in yet in set-up: the choice is recorded for this phone's device.
  const chooseText = async () => {
    setTextFailed(false);
    if ((await recordChannelForDevice('text')) === 'ok') router.push('/setup/done?channel=text');
    else setTextFailed(true);
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
      <h1 className={styles.title}>Add Overwatch to your home screen</h1>
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
      <StepCards label={`Add to home screen on ${platform}`} steps={steps} />
      {notInstalled ? (
        <Banner
          tone="warning"
          title="Open Overwatch from your home screen to carry on. Notifications only work from there."
        />
      ) : null}
      {textFailed ? <Banner tone="warning" title="We could not save that. Check your number again, then try once more." /> : null}
      <Button variant="primary" dataEl="ONB-HOME-ADDED-BTN" onClick={added}>
        I have added it
      </Button>
      <Button variant="neutral" dataEl="ONB-HOME-USETEXT-BTN" onClick={chooseText}>
        I cannot do this. Use text instead
      </Button>
    </main>
  );
}
