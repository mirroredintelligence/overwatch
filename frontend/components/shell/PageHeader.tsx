import type { ReactNode } from 'react';
import styles from './AppFrame.module.css';

// A page's own header, in the body: the title (an h1) when the top bar carries only the organisation, and the
// page-level actions on the right. Used by Overview, Organisations and Support.

export function PageHeader({ title, actions, children }: { title: string; actions?: ReactNode; children?: ReactNode }) {
  return (
    <div className={styles.pageHeader}>
      <div className={styles.pageHeaderText}>
        <h1 className={styles.pageTitle}>{title}</h1>
        {children}
      </div>
      {actions ? <div className={styles.pageActions}>{actions}</div> : null}
    </div>
  );
}
