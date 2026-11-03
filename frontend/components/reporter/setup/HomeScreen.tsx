'use client';

import { useRouter } from 'next/navigation';
import { useState, useSyncExternalStore, type ReactNode } from 'react';
import { Banner } from '@/components/ui/Banner';
import { ProviderShell } from '@/components/provider/ProviderShell';
import { recordChannelForDevice } from '@/lib/reporter/channel';
import setupStyles from './Setup.module.css';
import styles from './HomeScreen.module.css';

// Step 3 of 5 (W34): add Overwatch to the home screen. Notifications only work from the home screen, so
// a reporter who is already in the installed app is carried straight on.

type Platform = 'iPhone' | 'Android';

// Each step has the line under it that the artboard (R5, "Add to home screen") gives.
const CARRY_ON = 'Carry on there. Notifications only work from the home screen.';

type GuideStep = { key: string; title: string; hint: string; icon: ReactNode; dark?: boolean };

const SHARE_ICON = (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 15V4M8 8l4-4 4 4M6 12v8h12v-8" />
  </svg>
);
const ADD_ICON = (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="4" y="4" width="16" height="16" rx="3" />
    <path d="M12 8v8M8 12h8" />
  </svg>
);
const DOTS_ICON = (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
    <circle cx="12" cy="5" r="2" />
    <circle cx="12" cy="12" r="2" />
    <circle cx="12" cy="19" r="2" />
  </svg>
);
const MARK_ICON = (
  <svg width="24" height="24" viewBox="0 0 26 26">
    <circle cx="13" cy="13" r="10" fill="none" stroke="#fff" strokeWidth="2.4" />
    <circle cx="13" cy="13" r="4.2" fill="#fff" />
    <path d="M3 13h20" stroke="#fff" strokeWidth="2.4" />
  </svg>
);

const IPHONE_STEPS: GuideStep[] = [
  { key: 'share', title: 'Tap Share', hint: 'The square with an arrow, at the bottom of the screen', icon: SHARE_ICON },
  { key: 'add-to-home', title: 'Tap Add to Home Screen', hint: 'Scroll down the list if you cannot see it', icon: ADD_ICON },
  { key: 'add', title: 'Tap Add', hint: 'The Overwatch icon appears on your home screen', icon: <span className={styles.addWord}>Add</span> },
  { key: 'open', title: 'Open it from the home screen', hint: CARRY_ON, icon: MARK_ICON, dark: true },
];
const ANDROID_STEPS: GuideStep[] = [
  { key: 'menu', title: 'Open the browser menu', hint: 'Usually the three dots at the top of the screen', icon: DOTS_ICON },
  { key: 'install', title: 'Tap Install app or Add to Home screen', hint: 'Scroll down the menu if you cannot see it', icon: ADD_ICON },
  { key: 'open', title: 'Open Overwatch from the home screen', hint: CARRY_ON, icon: MARK_ICON, dark: true },
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
      <ProviderShell step={3} action={{ primary: { label: 'Continue', onClick: () => router.push('/setup/notifications') } }}>
        <div className={styles.stack}>
          <h1 className={setupStyles.title}>Welcome. Your set-up continues here.</h1>
        </div>
      </ProviderShell>
    );
  }

  const steps = platform === 'iPhone' ? IPHONE_STEPS : ANDROID_STEPS;
  return (
    <ProviderShell
      step={3}
      action={{
        primary: { label: 'I have added it', onClick: added },
        link: { label: 'I cannot do this. Use text instead', onClick: chooseText },
      }}
    >
      <div className={styles.stack}>
        <p className={setupStyles.caption}>Step 3 of 5</p>
        <h1 className={setupStyles.title}>Add Overwatch to your home screen</h1>
        <div role="tablist" aria-label="Your phone" className={styles.tabs}>
          {(['iPhone', 'Android'] as const).map((name) => (
            <button
              key={name}
              type="button"
              role="tab"
              aria-selected={platform === name}
              className={styles.tab}
              onClick={() => setPlatform(name)}
            >
              {name}
            </button>
          ))}
        </div>
        <ol aria-label={`Add to home screen on ${platform}`} className={styles.steps}>
          {steps.map((step, index) => (
            <li key={step.key} className={styles.step}>
              <span className={step.dark ? `${styles.icon} ${styles.iconDark}` : styles.icon} data-step-icon aria-hidden="true">
                {step.icon}
              </span>
              <span className={styles.stepBody}>
                <span className={styles.stepTitle}>
                  <span className={styles.stepNumber} aria-hidden="true">{`${index + 1}. `}</span>
                  {step.title}
                </span>
                <span className={styles.stepHint}>{step.hint}</span>
              </span>
            </li>
          ))}
        </ol>
        {platform === 'iPhone' ? <p className={styles.note}>iPhone needs iOS 16.4 or later.</p> : null}
        {notInstalled ? (
          <Banner
            tone="warning"
            title="Open Overwatch from your home screen to carry on. Notifications only work from there."
          />
        ) : null}
        {textFailed ? <Banner tone="warning" title="We could not save that. Check your number again, then try once more." /> : null}
      </div>
    </ProviderShell>
  );
}
