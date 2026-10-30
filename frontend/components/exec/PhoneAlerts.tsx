'use client';

import { useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { bffGet, bffPost } from '@/lib/bff/client';
import { subscribeToPush } from '@/lib/push/subscribe';
import styles from './Exec.module.css';

// Alerts on the executive's phone (W9H, DEC-1040 to DEC-1043). An executive uses the notification part of
// the installed app only: they hold no post and no PIN, so there is no capacity to report. Nothing is
// asked of the browser until Allow is pressed (consent first, then the browser's own prompt); the public
// key comes from the back end (it is the platform's, not a secret); the subscription goes to the BFF and
// nowhere else, so nothing is kept in the page or in storage. The consent wording is the executive's own
// (`exec-v1`): what they are sent is alerts about services, never a request to report.

const CONSENT_WORDING_VERSION = 'exec-v1';

type State = 'idle' | 'busy' | 'on' | 'blocked' | 'failed';

const TEST_MESSAGES: Record<number, string> = {
  409: 'No alerts are saved for this phone yet. Allow alerts first.',
  429: 'You have sent a few test notifications. Try again in a few minutes.',
};

function readKey(value: unknown): string {
  const key = (value as { publicKey?: unknown } | null)?.publicKey;
  if (typeof key !== 'string' || key === '') throw new Error('no key');
  return key;
}

export function PhoneAlerts() {
  const [state, setState] = useState<State>('idle');
  const [testNotice, setTestNotice] = useState<string | null>(null);
  const supported = typeof Notification !== 'undefined';

  const allow = async () => {
    setState('busy');
    setTestNotice(null);
    try {
      const permission = Notification.permission === 'granted' ? 'granted' : await Notification.requestPermission();
      if (permission !== 'granted') return setState('blocked');
      const key = await bffGet('/api/bff/push/key', readKey);
      if (!key.ok) return setState('failed');
      const registration = await navigator.serviceWorker.ready;
      const subscription = await subscribeToPush(registration, key.data);
      const saved = await bffPost('/api/bff/push/subscriptions', { subscription, consentWordingVersion: CONSENT_WORDING_VERSION });
      return setState(saved.ok && (saved.data as { saved?: unknown } | undefined)?.saved === true ? 'on' : 'failed');
    } catch {
      return setState('failed');
    }
  };

  const sendTest = async () => {
    const reply = await bffPost('/api/bff/push/test', {});
    if (reply.ok && (reply.data as { queued?: unknown } | undefined)?.queued === true) {
      return setTestNotice('A test notification is on its way.');
    }
    return setTestNotice(reply.ok ? 'We could not send a test notification. Try again.' : (TEST_MESSAGES[reply.status] ?? 'We could not send a test notification. Try again.'));
  };

  return (
    <div className={styles.stack}>
      <h1 className={styles.heading}>Alerts on this phone</h1>
      <section className={styles.section} aria-labelledby="phone-alerts-what">
        <h2 id="phone-alerts-what" className={styles.srOnly}>What this does</h2>
        <p>What we send: An alert about a service, as you chose in your alerts. It names the service and what changed.</p>
        <p>What we never send: Patient names or details.</p>
        <p>You choose: Change which alerts you get in settings, or turn them off in your phone’s settings.</p>
        <p>When you allow, we record the date and this phone.</p>
        <p>On an iPhone, alerts work only from the home screen. Tap Share, then Add to Home Screen, then open DIUCS from the home screen.</p>
      </section>

      {!supported ? <Banner tone="warning" title="This browser cannot show notifications. Open DIUCS in your phone’s browser, or install it to your home screen." /> : null}
      {state === 'blocked' ? <Banner tone="warning" title="Alerts are blocked for this phone. Turn them on in your phone’s settings, then try again." /> : null}
      {state === 'failed' ? <Banner tone="warning" title="We could not turn on alerts on this phone. Try again." /> : null}
      {state === 'on' ? <p role="status">Alerts are on for this phone.</p> : null}
      {testNotice !== null ? <p role="status">{testNotice}</p> : null}

      <div className={styles.actions}>
        {supported ? (
          <Button variant="primary" busy={state === 'busy'} onClick={() => void allow()} dataEl="EXEC-PHONE-ALLOW-BTN">
            Allow alerts on this phone
          </Button>
        ) : null}
        <Button variant="secondary" onClick={() => void sendTest()} dataEl="EXEC-PHONE-TEST-BTN">
          Send me a test notification
        </Button>
        <Button variant="secondary" href="/planning/settings" dataEl="EXEC-PHONE-SETTINGS-LINK">
          Change which alerts I get
        </Button>
        <Button variant="neutral" href="/planning" dataEl="EXEC-PHONE-DONE-LINK">
          Done
        </Button>
      </div>
    </div>
  );
}
