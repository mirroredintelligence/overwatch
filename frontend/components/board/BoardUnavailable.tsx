import styles from './Board.module.css';

// Shown when the board cannot be read at all. It shows no figure, because an
// old or guessed figure on a wall is worse than none, and says what to do. It
// looks like the offline banner (BoardDown) and offers nothing to press.
export function BoardUnavailable() {
  return (
    <main className={styles.board}>
      <div role="alert" className={styles.unavailable}>
        <span className={styles.unavailableMark} aria-hidden="true">
          !
        </span>
        <div>
          <h1 className={styles.unavailableTitle}>Board unavailable</h1>
          <p className={styles.unavailableText}>No figures can be shown. Use the whiteboard and phone process.</p>
        </div>
      </div>
      <footer className={styles.footer}>
        <p className={styles.privacy}>No patient information on this screen</p>
      </footer>
    </main>
  );
}
