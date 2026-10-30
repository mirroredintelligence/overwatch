import { Button } from '@/components/ui/Button';
import { StatusBadge } from '@/components/ui/StatusBadge';
import { londonHourMinute } from '@/lib/register/time';
import styles from '../register.module.css';

// Live (W27, ApprovalApplicant panel 6): the service is on the board, and its first prompt is due.

export function Live({ serviceName, firstPromptAt }: { serviceName: string; firstPromptAt?: string }) {
  return (
    <div className={styles.stack}>
      <span className={styles.complete}>Live</span>
      <h1 className={styles.heading}>You are live</h1>
      <p className={styles.text}>
        {firstPromptAt === undefined
          ? `The SPOA can now see ${serviceName} on the board.`
          : `The SPOA can now see ${serviceName} on the board. Your first prompt arrives at ${londonHourMinute(firstPromptAt)}.`}
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
    </div>
  );
}
