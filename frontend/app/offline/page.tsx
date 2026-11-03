'use client';

import styles from './Offline.module.css';

// The offline shell (W32). It is the only page the service worker precaches, so it holds no
// tenant, service or capacity data: the coordination team number differs per organisation and cannot be shown
// here (DEC-660 item 3). Try again reloads the page; the shell comes back from the cache when the connection does not.
export default function OfflinePage() {
  return (
    <main className={styles.page}>
      <section className={styles.card} aria-labelledby="offline-heading">
        <span className={styles.icon} aria-hidden="true">
          <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="#7A3500" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M2 8.5a15 15 0 0 1 20 0M5 12a10 10 0 0 1 14 0M8.5 15.5a5 5 0 0 1 7 0M12 19h.01M3 3l18 18" />
          </svg>
        </span>
        <h1 id="offline-heading" className={styles.title}>
          No connection
        </h1>
        <p className={styles.text}>
          Capacity cannot be shown without a connection. Use the phone process: phone the coordination team on the
          number your service has on record.
        </p>
        <div className={styles.notice}>
          <b>Nothing shown here is current.</b> A figure that cannot be refreshed is never shown as if it were.
        </div>
        <div className={styles.actions}>
          <button type="button" className={styles.primary} onClick={() => window.location.reload()}>
            Try again
          </button>
        </div>
      </section>
    </main>
  );
}
