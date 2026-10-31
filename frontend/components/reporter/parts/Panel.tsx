import type { ReactNode } from 'react';
import styles from './Parts.module.css';

/** A quiet boxed line, for a fact the person should see apart from the text (the next update due). */
export function Panel({ children, dataEl }: { children: ReactNode; dataEl?: string }) {
  return (
    <p className={styles.panel} data-el={dataEl}>
      {children}
    </p>
  );
}
