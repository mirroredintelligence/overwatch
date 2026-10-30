import Link from 'next/link';
import styles from '../console/Console.module.css';

// "Need a hand?" (W53). The coordination team number comes from the service's own record, never from a constant:
// with no number set, the panel says so rather than showing one.

export function HelpPanel({ spoaPhone, champion }: { spoaPhone: string | null; champion?: string }) {
  return (
    <section className={styles.section} aria-labelledby="help-heading">
      <h2 id="help-heading" className={styles.heading}>Need a hand?</h2>
      <ul>
        <li><Link href="/help">Read the one-page guide</Link></li>
        <li>Ask your champion{champion ? `, ${champion}` : ''}</li>
        <li>
          Phone the shift lead:{' '}
          {spoaPhone !== null ? <span>{spoaPhone}</span> : <span>The number is not set for your service yet. Ask your shift lead.</span>}
        </li>
        <li><Link href="/help/problem">Report a problem</Link></li>
      </ul>
      <p className={styles.help}>Help is one tap away on every screen.</p>
    </section>
  );
}
