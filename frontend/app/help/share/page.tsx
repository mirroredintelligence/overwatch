import type { Metadata } from 'next';
import { SupportCode } from '@/components/help/SupportCode';
import styles from '@/components/help/Help.module.css';

export const metadata: Metadata = { title: 'Your support code - Overwatch', robots: { index: false } };

// The person's own support code (W56). The page is the person's; it names nothing else.
export default function SharePage() {
  return (
    <main className={`${styles.card} ${styles.cardPlain}`} data-help-form>
      <SupportCode />
    </main>
  );
}
