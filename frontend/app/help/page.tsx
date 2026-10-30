import type { Metadata } from 'next';
import { Button } from '@/components/ui/Button';
import { supportSharingOn } from '@/lib/help/report';
import styles from '@/components/exec/Exec.module.css';

export const metadata: Metadata = { title: 'Help - DIUCS capacity' };

// The help page (W46). "Share my session with support" is behind the flag until W56 turns it on.
export default function HelpPage() {
  return (
    <main className={styles.stack}>
      <h1 className={styles.heading}>Help</h1>
      <p>Help is one tap away on every screen.</p>
      <div className={styles.actions}>
        <Button variant="primary" href="/help/safety" dataEl="HELP-SAFETY-BTN">Report a safety concern</Button>
        <Button variant="secondary" href="/help/problem" dataEl="HELP-PROBLEM-BTN">Something is wrong with the tool</Button>
        {supportSharingOn() ? (
          <Button variant="secondary" href="/help/share" dataEl="HELP-SHARE-BTN">Share my session with support</Button>
        ) : null}
      </div>
    </main>
  );
}
