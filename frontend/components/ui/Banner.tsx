import type { ReactNode } from 'react';
import styles from './Banner.module.css';

export type BannerTone = 'info' | 'warning' | 'offline';

export type BannerProps = {
  tone: BannerTone;
  title: string;
  children?: ReactNode;
  dataEl?: string;
};

export function Banner({ tone, title, children, dataEl }: BannerProps) {
  return (
    <div
      className={`${styles.banner} ${styles[tone]}`}
      role={tone === 'info' ? 'status' : 'alert'}
      data-tone={tone}
      data-el={dataEl}
    >
      <p className={styles.title}>{title}</p>
      {children !== undefined ? <div className={styles.body}>{children}</div> : null}
    </div>
  );
}
