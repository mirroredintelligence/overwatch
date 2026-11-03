import { Button } from '@/components/ui/Button';
import { StatusBadge } from '@/components/ui/StatusBadge';
import { StatusTag } from '@/components/ui/StatusTag';
import { londonHourMinute } from '@/lib/register/time';
import styles from '../status.module.css';

// Live (W27, ApprovalApplicant panel 6): the service is on the board, and its first prompt is due.

export function Live({ serviceName, firstPromptAt }: { serviceName: string; firstPromptAt?: string }) {
  return (
    <section className={styles.card} aria-label="Live">
      <div className={styles.tagRow}>
        <StatusTag variant="live">Live</StatusTag>
      </div>
      <h1 className={styles.heading}>You are live</h1>
      <p className={styles.text}>
        {firstPromptAt === undefined
          ? `The coordination team can now see ${serviceName} on the board.`
          : `The coordination team can now see ${serviceName} on the board. Your first prompt arrives at ${londonHourMinute(firstPromptAt)}.`}
      </p>
      <div className={styles.tile} role="group" aria-label="How it looks on the board">
        <p className={styles.tileTitle}>How it looks on the board</p>
        <p className={styles.tileName}>{serviceName}</p>
        <StatusBadge status="accepting" />
      </div>
      <div className={styles.actions}>
        <Button variant="primary" href="/" dataEl="REG-STATUS-APP-BTN">
          Go to the app
        </Button>
      </div>
    </section>
  );
}
