import styles from './Board.module.css';

// Shown when the board cannot be read at all. It shows no figure, because an
// old or guessed figure on a wall is worse than none, and says what to do.
export function BoardUnavailable() {
  return (
    <main className={styles.board}>
      <div role="alert" className={styles.unavailable}>
        <h1 className={styles.title}>Board unavailable</h1>
        <p className={styles.subtitle}>No figures can be shown. Use the whiteboard and phone process.</p>
      </div>
      <footer className={styles.footer}>
        <p className={styles.privacy}>No patient information on this screen</p>
      </footer>
    </main>
  );
}
