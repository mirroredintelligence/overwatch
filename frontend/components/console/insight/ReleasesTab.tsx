import type { Compare, Measure, PipelineRow } from '@/lib/console/insight';
import styles from '../Console.module.css';

// Release comparison and pipeline health (W49). The change is a word: slower or faster, higher or
// lower, no change.

export function changeWord(measure: Measure): string {
  if (measure.new === measure.old) return 'No change';
  if (measure.unit === 'ms') return measure.new > measure.old ? 'Slower' : 'Faster';
  return measure.new > measure.old ? 'Higher' : 'Lower';
}

export function ReleasesTab({
  compare,
  measures,
  pipeline,
}: {
  compare: Compare | null;
  measures: readonly Measure[];
  pipeline: readonly PipelineRow[];
}) {
  return (
    <div className={styles.page}>
      {compare !== null && (
        <p>
          Comparing {compare.new} with {compare.old}
        </p>
      )}
      <table className={styles.table} aria-label="Release comparison">
        <thead>
          <tr>
            <th scope="col">Measure</th>
            <th scope="col">Old</th>
            <th scope="col">New</th>
            <th scope="col">Change</th>
          </tr>
        </thead>
        <tbody>
          {measures.map((measure) => (
            <tr key={measure.measure}>
              <td>{measure.measure}</td>
              <td>{measure.old}</td>
              <td>{measure.new}</td>
              <td>{changeWord(measure)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <table className={styles.table} aria-label="Pipeline health">
        <thead>
          <tr>
            <th scope="col">Queue or topic</th>
            <th scope="col">Active</th>
            <th scope="col">Dead-lettered</th>
            <th scope="col">Oldest</th>
          </tr>
        </thead>
        <tbody>
          {pipeline.map((row) => (
            <tr key={row.name}>
              <td>{row.name}</td>
              <td>{row.active}</td>
              <td>{row.deadLettered}</td>
              <td>{row.oldestSeconds === null ? 'None' : `${row.oldestSeconds} s`}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className={styles.help}>A dead-lettered message raises an alert to engineering.</p>
    </div>
  );
}
