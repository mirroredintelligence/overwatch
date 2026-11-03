import type { Metadata } from 'next';
import Link from 'next/link';
import styles from './Forbidden.module.css';

export const metadata: Metadata = {
  title: 'No access - Overwatch',
  robots: { index: false },
};

// Shown, by the proxy, to a signed-in person whose role may not open the page they asked for. It names
// no page, role or organisation: what the page is, or who may see it, is not told to someone who may not.
export default function ForbiddenPage() {
  return (
    <main className={styles.page}>
      <section className={styles.card} aria-labelledby="forbidden-heading" data-el="FORBIDDEN">
        <span className={styles.icon} aria-hidden="true">
          <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="#3A4750" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="5" y="11" width="14" height="9" rx="2" />
            <path d="M8 11V8a4 4 0 0 1 8 0v3" />
          </svg>
        </span>
        <h1 id="forbidden-heading" className={styles.heading}>
          You do not have access to this page.
        </h1>
        <p className={styles.text}>Ask your shift lead to check your access.</p>
        <div className={styles.actions}>
          <Link href="/" className={styles.primary}>
            Back to my home
          </Link>
          <Link href="/sign-in" className={styles.secondary}>
            Sign in as someone else
          </Link>
        </div>
      </section>
    </main>
  );
}
