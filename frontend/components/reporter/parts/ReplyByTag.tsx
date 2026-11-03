import styles from './ReplyByTag.module.css';

// "Reply by 10:30" with a clock (artboards B1, B2, B7, D1). A fixed time, never a countdown: the clock is a
// picture only and the words carry the meaning.

export function ReplyByTag({ time, dataEl }: { time: string; dataEl?: string }) {
  return (
    <span className={styles.tag} data-el={dataEl}>
      <svg width="16" height="16" viewBox="0 0 20 20" aria-hidden="true" focusable="false">
        <circle cx="10" cy="10" r="8" fill="none" stroke="currentColor" strokeWidth="2" />
        <path d="M10 5.5V10l3 2" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      </svg>
      {`Reply by ${time}`}
    </span>
  );
}
