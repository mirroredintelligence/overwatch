'use client';

import { useState } from 'react';
import { requestRenew } from '@/lib/links/browser';
import styles from './CapacityLink.module.css';
import { LinkFrame } from './parts/LinkFrame';
import { StateBanner, type StateBannerTone } from './parts/StateBanner';

// The page for a link that has expired or been used (artboard B3, board 1). It says the same thing for both,
// and for a link the back end does not know: the page never tells which of them it was.

type Phase = 'idle' | 'busy' | 'sent' | 'rate-limited' | 'failed';

const RESULT: Partial<Record<Phase, { tone: StateBannerTone; text: string }>> = {
  sent: { tone: 'info', text: 'We have sent a new link.' },
  'rate-limited': { tone: 'warning', text: 'Too many new links. Wait a few minutes, then try again.' },
  failed: { tone: 'error', text: 'We could not send a new link. Try again.' },
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
    <LinkFrame noLoginTag={false}>
      <main className={styles.stack}>
        <section className={`${styles.card} ${styles.cardStart}`}>
          <span className={`${styles.tag} ${styles.tagDashed}`} data-el="REP-LINK-EXPIRED-MARK" data-tone="closed">
            <svg width="16" height="16" viewBox="0 0 20 20" aria-hidden="true" focusable="false">
              <circle cx="10" cy="10" r="8" fill="none" stroke="currentColor" strokeWidth="2" />
              <path d="M10 5.5V10l3 2" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
            Link closed
          </span>
          <h1 className={styles.heading}>This link has expired</h1>
          <p className={styles.body}>This link can no longer be used.</p>
        </section>
        {phase !== 'sent' && csrfToken !== null ? (
          <button
            type="button"
            className={`${styles.btn} ${styles.primary}`}
            disabled={phase === 'busy'}
            aria-busy={phase === 'busy' ? 'true' : undefined}
            data-el="REP-LINK-RENEW-BTN"
            onClick={renew}
          >
            Send me a new link
          </button>
        ) : null}
        {result !== undefined ? <StateBanner tone={result.tone} lead={result.text} /> : null}
        <p className={styles.aside}>Or reply to the text message instead.</p>
        <section className={`${styles.card} ${styles.cardPlain}`}>
          <p className={styles.asideHead}>If it says “already used”</p>
          <p className={styles.asideText}>A link works once. If you already sent your update, you will find it on the board.</p>
        </section>
      </main>
    </LinkFrame>
  );
}
