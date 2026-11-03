import type { ReactNode } from 'react';
import styles from './FigureCard.module.css';
import { ReplyByTag } from './ReplyByTag';

// The card every capacity step shares (artboards B1, B2, B7, D1; brief Rule 1): service, label, reply-by tag,
// the 96px figure with its unit, and when it was recorded. The figure stays in the same place and size on every
// step and never animates: this component and its style sheet have no transition, so nothing here can move it.
// Only the controls placed around it open and close.

export type FigureCardProps = {
  service: string;
  /** The small line above the service, like "Capacity update". */
  label?: string;
  /** A time like "10:30". Shown as "Reply by 10:30". */
  replyBy?: string;
  /** Left out on a first report, when nothing is recorded yet. 0 is a figure. */
  figure?: number | null;
  /** What the figure counts, like "referrals in the next 2 hours". */
  unit?: string;
  recordedAt?: string;
  /** A question after the recorded time, like "Still right?". */
  recordedNote?: string;
  headingLevel?: 1 | 2;
  /** Words under the heading when there is no figure yet. */
  children?: ReactNode;
  dataEl?: string;
  /** Larger type for a laptop (artboard D1). */
  large?: boolean;
};

export function FigureCard({ service, label, replyBy, figure, unit, recordedAt, recordedNote, headingLevel = 1, children, dataEl, large = false }: FigureCardProps) {
  const Heading = headingLevel === 1 ? 'h1' : 'h2';
  const hasFigure = figure !== undefined && figure !== null;
  const recorded = recordedAt === undefined ? null : `Recorded at ${recordedAt}${recordedNote ? `. ${recordedNote}` : ''}`;
  return (
    <div className={`${styles.card} ${large ? styles.large : ''}`} data-el={dataEl}>
      {label !== undefined || replyBy !== undefined ? (
        <div className={styles.top}>
          {label !== undefined ? <span className={styles.label}>{label}</span> : <span />}
          {replyBy !== undefined ? <ReplyByTag time={replyBy} /> : null}
        </div>
      ) : null}
      <Heading className={styles.service}>{service}</Heading>
      {children !== undefined && !hasFigure ? <div className={styles.prompt}>{children}</div> : null}
      {hasFigure ? (
        <p className={styles.figureRow}>
          <span className={styles.figure} data-figure={String(figure)}>
            {figure}
          </span>
          {unit !== undefined ? <span className={styles.unit}>{unit}</span> : null}
        </p>
      ) : null}
      {recorded !== null ? <p className={styles.recorded}>{recorded}</p> : null}
    </div>
  );
}
