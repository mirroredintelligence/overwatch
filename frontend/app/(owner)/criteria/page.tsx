import type { Metadata } from 'next';
import Link from 'next/link';
import { redirect } from 'next/navigation';
import { getSession } from '@/lib/auth/session';
import styles from '@/components/lead/lead-forms.module.css';
import landing from './landing.module.css';

export const metadata: Metadata = {
  title: 'Your services · Overwatch',
};

export const dynamic = 'force-dynamic';

// The criteria owner's landing (DEC-1310, boards/lead/Patterns "Owner with several services"): the services the
// signed-in person can review, from the session's own list. One service goes straight to its overview, none says
// so and points to Help. The session carries the service ids only, so each row shows the id and no review-by date,
// and the list is in the session's order, not by what is due: the overview has the date.
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
          <p className={styles.lede} role="status">
            No services to review
          </p>
          <p className={styles.hint}>
            <Link href="/help">Help</Link>
          </p>
        </>
      ) : (
        <ul className={styles.list} aria-label="Your services">
          {services.map((id) => (
            <li key={id} className={styles.card}>
              <Link href={`/criteria/${encodeURIComponent(id)}`} className={landing.row}>
                <span className={styles.name}>{id}</span>
                <span className={landing.chevron} aria-hidden="true">
                  ›
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
