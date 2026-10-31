import type { Compare, Measure, PipelineRow } from '@/lib/console/insight';
import styles from '../Console.module.css';

// Release comparison and pipeline health (W49, W9F). The change is a word: slower or faster, higher or
// lower, no change; a change the release gate holds says so in words as well.

export function changeWord(measure: Measure): string {
  if (measure.new === measure.old) return 'No change';
  if (measure.unit === 'ms') return measure.new > measure.old ? 'Slower' : 'Faster';
  return measure.new > measure.old ? 'Higher' : 'Lower';
}

function show(value: number, unit: Measure['unit']): string {
  if (unit === 'ms') return `${Math.round(value)} ms`;
  if (unit === 'percent') return `${value}%`;
  return String(value);
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
      {compare === null ? (
        <p className={styles.help}>Two releases with at least 10 sessions each are needed to compare.</p>
      ) : (
        <p>
          Comparing {compare.new} with {compare.old}
        </p>
      )}
      {compare !== null && (
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
              <td>{show(measure.old, measure.unit)}</td>
              <td>{show(measure.new, measure.unit)}</td>
              <td>
                {changeWord(measure)}
                {measure.review === true && (
                  <>
                    {'. '}
                    <span><span aria-hidden="true">▲ </span>Held for review</span>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      )}
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
