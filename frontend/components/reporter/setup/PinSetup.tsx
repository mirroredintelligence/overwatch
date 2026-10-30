'use client';

import { useRouter } from 'next/navigation';
import { useRef, useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { bffRequest } from '@/lib/reporter/browser';
import { PinPad } from '../PinPad';
import styles from './Setup.module.css';

// Step 5 of 5 (W34): create the PIN, enter it again, then sign in with it. The PIN is held only in
// this component for the two entries; it is sent once, to the BFF, and never stored in the browser.

const MISMATCH = 'The PINs do not match. Try again.';

export function PinSetup() {
  const router = useRouter();
  const [stage, setStage] = useState<'create' | 'confirm'>('create');
  const [first, setFirst] = useState('');
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const sending = useRef(false);

  const restart = () => {
    setStage('create');
    setFirst('');
  };

  const setPin = async (pin: string) => {
    if (sending.current) return;
    sending.current = true;
    setBusy(true);
    const set = await bffRequest('/api/bff/identity/pin', { method: 'POST', body: { pin } });
    if (set.status !== 200) {
      sending.current = false;
      setBusy(false);
      setNotice(set.status === 403 ? 'Get a code by text first.' : 'We could not set your PIN. Try again.');
      return;
    }
    const signIn = await bffRequest('/api/bff/identity/pin/verify', { method: 'POST', body: { pin } });
    if (signIn.status === 200) {
      router.push('/setup/all-set');
      return;
    }
    sending.current = false;
    setBusy(false);
    setNotice('We could not sign you in. Try again.');
  };

  const onComplete = (pin: string) => {
    setNotice(null);
    if (stage === 'create') {
      setFirst(pin);
      setStage('confirm');
      return;
    }
    if (pin !== first) {
      setNotice(MISMATCH);
      restart();
      return;
    }
    void setPin(pin);
  };

  return (
    <main className={styles.page}>
      <p className={styles.caption}>Step 5 of 5</p>
      <h1 className={styles.title}>{stage === 'create' ? 'Create a 6-digit PIN' : 'Enter it again'}</h1>
      {stage === 'create' ? (
        <p>You enter it each time you open the app. We text you a code again every 30 days.</p>
      ) : null}
      {notice !== null ? <Banner tone="warning" title={notice} /> : null}
      <PinPad label={stage === 'create' ? 'Create a 6-digit PIN' : 'Enter it again'} onComplete={onComplete} dataEl="ONB" />
      {busy ? <p role="status">Saving your PIN</p> : null}
    </main>
  );
}
