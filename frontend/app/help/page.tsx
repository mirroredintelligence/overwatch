import type { Metadata } from 'next';
import { HelpPanel } from '@/components/learn/HelpPanel';
import styles from '@/components/exec/Exec.module.css';

export const metadata: Metadata = { title: 'Help - Overwatch' };

// The help page (W46; the share link is on for everyone since W56). The three ways in are the hub column
// of the layout; this is what sits beside it.
export default function HelpPage() {
  return (
    <main className={styles.stack} data-help-hub>
      <h1 className={styles.heading}>Help</h1>
      <p>Works signed in or out. Nothing here asks for patient details.</p>
      <HelpPanel spoaPhone={null} />
    </main>
  );
}
