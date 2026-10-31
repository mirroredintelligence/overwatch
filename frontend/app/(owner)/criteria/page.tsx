import type { Metadata } from 'next';
import Link from 'next/link';
import { redirect } from 'next/navigation';
import { getSession } from '@/lib/auth/session';
import styles from '@/components/lead/lead-forms.module.css';

export const metadata: Metadata = {
  title: 'Your services · Overwatch',
};

export const dynamic = 'force-dynamic';

// The criteria owner's landing (DEC-1306): the services the signed-in person can review, from the
// session's own list. The design has no landing screen (the owner arrives from a reminder link), so
// this stays plain: one service goes straight to its overview, none says so. The session carries the
// service ids only, so no review-by date is shown here; the overview has it.
const REVIEWERS = ['owner', 'clinical', 'lead'];

export default async function CriteriaLandingPage() {
  const session = await getSession();
  if (!session || !REVIEWERS.includes(session.role)) redirect('/sign-in');
  const services = session.services;
  if (services.length === 1) redirect(`/criteria/${encodeURIComponent(services[0])}`);
  return (
    <main className={styles.page}>
      <h1 className={styles.heading}>Your services</h1>
      {services.length === 0 ? (
        <>
          <p className={styles.lede}>No services to review</p>
          <p className={styles.hint}>
            <Link href="/help">Help</Link>
          </p>
        </>
      ) : (
        <ul className={styles.list}>
          {services.map((id) => (
            <li key={id} className={styles.card}>
              <Link href={`/criteria/${encodeURIComponent(id)}`} className={styles.name}>
                {id}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
