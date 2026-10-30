import type { Metadata } from 'next';
import { ReviewList } from '@/components/register/ReviewList';
import styles from '@/components/register/register.module.css';

// Registration step 5, the review (W26). The sections are read through the BFF.

export const metadata: Metadata = {
  title: 'Check your details - DIUCS capacity',
  robots: { index: false },
};

export default async function ReviewPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <main className={styles.main}>
      <div className={styles.panel}>
        <div className={styles.card}>
          <ReviewList registrationId={id} />
        </div>
      </div>
    </main>
  );
}
