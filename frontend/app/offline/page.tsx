import styles from './Offline.module.css';

// The offline shell (W32). It is the only page the service worker precaches, so it holds no
// tenant, service or capacity data: the coordination team number differs per organisation and cannot be shown
// here (DEC-660 item 3).
export default function OfflinePage() {
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>No connection</h1>
      <p>
        Capacity cannot be shown without a connection. Use the phone process: phone the coordination team on the
        number your service has on record.
      </p>
    </main>
  );
}
