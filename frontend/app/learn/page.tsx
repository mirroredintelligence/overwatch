import type { Metadata } from 'next';
import { HelpPanel } from '@/components/learn/HelpPanel';
import { LearnLibrary } from '@/components/learn/LearnLibrary';
import styles from '@/components/console/Console.module.css';

export const metadata: Metadata = {
  title: 'DIUCS capacity: lessons',
};

// The library holds no person's data, so it is public and needs no session.
export default function LearnPage() {
  return (
    <main className={styles.page}>
      <LearnLibrary />
      <HelpPanel spoaPhone={null} />
    </main>
  );
}
