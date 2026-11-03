import styles from './FigureStrip.module.css';

// The last five figures a service reported, oldest first (the "last reports" strip on the Reports to check
// board). It draws nothing when there are no figures, so a screen can mount it before the data exists.

export type Figure = { value: number; time: string };

export type FigureStripProps = {
  figures: readonly Figure[];
  /** A line beside the figures, for example the usual range. */
  note?: string;
};

const SHOWN = 5;

export function FigureStrip({ figures, note }: FigureStripProps) {
  if (figures.length === 0) return null;
  return (
    <div className={styles.strip}>
      <div className={styles.label}>The last reports</div>
      <div className={styles.row}>
        <ol className={styles.figures}>
          {figures.slice(-SHOWN).map((figure, index) => (
            <li key={`${figure.time}-${index}`} className={styles.figure}>
              <span className={styles.value}>{figure.value}</span>
              <span className={styles.time}>{figure.time}</span>
            </li>
          ))}
        </ol>
        {note !== undefined ? <p className={styles.note}>{note}</p> : null}
      </div>
    </div>
  );
}
