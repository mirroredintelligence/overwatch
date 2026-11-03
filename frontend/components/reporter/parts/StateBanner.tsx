import type { ReactNode } from 'react';
import styles from './StateBanner.module.css';

// The shared states (artboard St): bad signal, something went wrong, a warning, success. A picture, a bold
// lead, and what was kept ("Nothing has been lost. Your number is still here."). Each tone has its own shape
// as well as its own colour. 'offline' and 'error' are announced at once (role alert); 'warning' and 'info'
// politely (role status). 'info' springs in once (it is the success message); the figure beside it never moves.

export type StateBannerTone = 'offline' | 'error' | 'warning' | 'info';

const PICTURE: Record<StateBannerTone, ReactNode> = {
  offline: (
    <>
      <path d="M2 8.5a15 15 0 0 1 20 0M5 12.5a10 10 0 0 1 14 0M8.5 16.5a5 5 0 0 1 7 0M12 20h.01" />
      <path d="M3 3l18 18" />
    </>
  ),
  error: (
    <>
      <path d="M12 3l10 18H2z" />
      <path d="M12 10v5M12 18.2h.01" />
    </>
  ),
  warning: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7.5v5.5M12 16.2h.01" />
    </>
  ),
  info: <path d="M5 12.5l4.5 4.5L19 7.5" />,
};

export function StateBanner({ tone, lead, children, dataEl }: { tone: StateBannerTone; lead: string; children?: ReactNode; dataEl?: string }) {
  const role = tone === 'offline' || tone === 'error' ? 'alert' : 'status';
  return (
    <div className={`${styles.banner} ${styles[tone]}`} role={role} data-tone={tone} data-el={dataEl}>
      <span className={styles.picture}>
        <svg width={tone === 'info' ? 22 : 26} height={tone === 'info' ? 22 : 26} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={tone === 'info' ? 2.6 : 2.2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
          {PICTURE[tone]}
        </svg>
      </span>
      <p className={styles.words}>
        <strong>{lead}</strong>
        {children !== undefined ? <> {children}</> : null}
      </p>
    </div>
  );
}
