import type { Metadata } from 'next';
import { OrganisationForm } from '@/components/register/OrganisationForm';
import styles from '@/components/register/register.module.css';

// Registration step 1, the organisation (W54). The form loads the invitation through the BFF.

export const metadata: Metadata = {
  title: 'Your organisation - DIUCS capacity',
  robots: { index: false },
};

export default async function OrganisationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <main className={styles.main}>
      <div className={styles.panel}>
        <div className={styles.card}>
          <OrganisationForm registrationId={id} />
        </div>
      </div>
    </main>
  );
}
