import Link from 'next/link';
import { StatusTag, type StatusTagVariant } from '@/components/ui/StatusTag';
import styles from './TaskRow.module.css';

// One thing that needs a person (admin overview, A1): a status tag, the title, one line, one action.
// The action is a button, or a link when it has an href. `urgent` draws the amber frame of a thing waiting on
// the person; `primary` makes the action the filled one (one per screen).

export type TaskAction = {
  label: string;
  onClick?: () => void;
  href?: string;
  primary?: boolean;
};

export type TaskRowProps = {
  status: StatusTagVariant;
  statusWord: string;
  title: string;
  line: string;
  action: TaskAction;
  urgent?: boolean;
};

export function TaskRow({ status, statusWord, title, line, action, urgent }: TaskRowProps) {
  const actionClass = `${styles.action} ${action.primary ? styles.primary : ''}`;
  return (
    <div className={styles.row} data-urgent={urgent ? 'true' : undefined}>
      <StatusTag variant={status}>{statusWord}</StatusTag>
      <div className={styles.text}>
        <div className={styles.title}>{title}</div>
        <div className={styles.line}>{line}</div>
      </div>
      {action.href ? (
        <Link href={action.href} className={actionClass} data-primary={action.primary ? 'true' : undefined}>
          {action.label}
        </Link>
      ) : (
        <button type="button" className={actionClass} data-primary={action.primary ? 'true' : undefined} onClick={action.onClick}>
          {action.label}
        </button>
      )}
    </div>
  );
}
