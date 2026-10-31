import styles from './Parts.module.css';

// The round mark at the top of a result page (artboards Reporter "Confirmation", Reporter2 "expired",
// BookingExceptions "withdrawn"). The meaning is in the page's heading; the mark is a picture only and is
// hidden from a screen reader. 'done' is a tick on the primary colour, 'closed' is a dashed clock on grey.

export type StatusMarkTone = 'done' | 'closed';

export function StatusMark({ tone, dataEl }: { tone: StatusMarkTone; dataEl?: string }) {
  return (
    <div className={`${styles.mark} ${tone === 'closed' ? styles.markClosed : ''}`} aria-hidden="true" data-el={dataEl} data-tone={tone}>
      <svg width="48" height="48" viewBox="0 0 30 30" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
        {tone === 'done' ? (
          <>
            <circle cx="15" cy="15" r="12" />
            <path d="M9.5 15.5l4 4 7-8" />
          </>
        ) : (
          <>
            <circle cx="15" cy="15" r="12" strokeDasharray="4 4" />
            <path d="M15 8.5V15l4 2.5" />
          </>
        )}
      </svg>
    </div>
  );
}
