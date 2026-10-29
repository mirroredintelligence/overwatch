import type { Metadata } from 'next';
import styles from '../sign-in/page.module.css';

export const metadata: Metadata = {
  title: 'No access - DIUCS capacity',
  robots: { index: false },
};

// Shown, by the proxy, to a signed-in person whose role may not open the page they asked for. It names
// no page, role or organisation: what the page is, or who may see it, is not told to someone who may not.
export default function ForbiddenPage() {
  return (
    <main className={styles.main}>
      <div className={styles.panel}>
        <section className={styles.card} aria-labelledby="forbidden-heading" data-el="FORBIDDEN">
          <h1 id="forbidden-heading" className={styles.heading}>
            You do not have access to this page.
          </h1>
          <p className={styles.text}>Ask your shift lead to check your access.</p>
        </section>
      </div>
    </main>
  );
}
