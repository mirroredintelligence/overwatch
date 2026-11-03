import type { Metadata } from 'next';
import { ProblemForm } from '@/components/help/ProblemForm';
import styles from '@/components/help/Help.module.css';
import { pagePath } from '@/lib/help/report';

export const metadata: Metadata = { title: 'Something is wrong with the tool - Overwatch' };

// The page the person came from is the `from` query (a page path), so the report says where it happened.
export default async function ProblemPage({ searchParams }: { searchParams: Promise<{ from?: string }> }) {
  const query = await searchParams;
  return (
    <main className={styles.card} data-help-form>
      <h1 className={styles.cardTitle}>Something is wrong with the tool</h1>
      <ProblemForm from={pagePath(query.from)} />
    </main>
  );
}
