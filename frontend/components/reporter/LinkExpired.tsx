'use client';

import { useState } from 'react';
import { Banner } from '@/components/ui/Banner';
import { Button } from '@/components/ui/Button';
import { requestRenew } from '@/lib/links/browser';
import styles from './Reporter.module.css';

// The page for a link that has expired or been used. It says the same thing for both, and for a
// link the back end does not know: the page never tells which of them it was.

type Phase = 'idle' | 'busy' | 'sent' | 'rate-limited' | 'failed';

const RESULT: Partial<Record<Phase, { tone: 'info' | 'warning'; text: string }>> = {
  sent: { tone: 'info', text: 'We have sent a new link.' },
  'rate-limited': { tone: 'warning', text: 'Too many new links. Wait a few minutes, then try again.' },
  failed: { tone: 'warning', text: 'We could not send a new link. Try again.' },
};

/**
 * `csrfToken` is the renewal token the closed link's answer gave the page (KI-178). With none, a new link is
 * not offered and the person is told to reply to the text.
 */
export function LinkExpired({ token, csrfToken }: { token: string; csrfToken: string | null }) {
  const [phase, setPhase] = useState<Phase>('idle');

  async function renew() {
    if (csrfToken === null) return;
    setPhase('busy');
    const result = await requestRenew(token, csrfToken);
    setPhase(result === 'accepted' ? 'sent' : result === 'rate-limited' ? 'rate-limited' : 'failed');
  }

  const result = RESULT[phase];
  return (
    <main className={styles.page}>
      <p className={styles.eyebrow}>DIUCS capacity update</p>
      <h1 className={styles.title}>This link has expired</h1>
      <p className={styles.question}>This link can no longer be used.</p>
      {phase !== 'sent' && csrfToken !== null ? (
        <Button variant="primary" busy={phase === 'busy'} dataEl="REP-LINK-RENEW-BTN" onClick={renew}>
          Send me a new link
        </Button>
      ) : null}
      {result !== undefined ? <Banner tone={result.tone} title={result.text} /> : null}
      <p className={styles.or}>Or reply to the text message instead.</p>
      <p className={styles.footer}>A link works once. If you already sent your update, you will find it on the board.</p>
    </main>
  );
}
