import type { ReactNode } from 'react';
import { Icon } from '@/components/shell/icons';
import { StatusTag, type StatusTagVariant } from '@/components/ui/StatusTag';
import styles from './ContactRow.module.css';

// One contact line (admin Contacts, A4): icon, label and value, status, and Edit/Add. While `editing`, the
// children (the form) open in place under the header and the action is gone; the form owns Save and Cancel.

export type ContactRowProps = {
  kind: 'phone' | 'mail';
  label: string;
  value: ReactNode;
  status: StatusTagVariant;
  statusWord: string;
  actionLabel?: string;
  onAction?: () => void;
  // Name the action with the label too ("Edit Support email") for a list of identical buttons.
  nameAction?: boolean;
  editing?: boolean;
  children?: ReactNode;
};

export function ContactRow({ kind, label, value, status, statusWord, actionLabel, onAction, nameAction, editing, children }: ContactRowProps) {
  return (
    <div className={styles.row} data-editing={editing ? 'true' : undefined}>
      <div className={styles.head}>
        <span className={styles.icon}>
          <Icon name={kind === 'phone' ? 'phone' : 'mail'} />
        </span>
        <div className={styles.text}>
          <div className={styles.label}>{label}</div>
          <div className={styles.value}>{value}</div>
        </div>
        <StatusTag variant={status}>{statusWord}</StatusTag>
        {!editing && actionLabel ? (
          <button type="button" className={styles.action} onClick={onAction} aria-label={nameAction ? `${actionLabel} ${label}` : undefined}>
            {actionLabel}
          </button>
        ) : null}
      </div>
      {editing ? <div className={styles.form}>{children}</div> : null}
    </div>
  );
}
