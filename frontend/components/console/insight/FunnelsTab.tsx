import { biggestDrop, type FunnelStep } from '@/lib/console/funnel';
import type { Funnel } from '@/lib/console/insight';
import styles from '../Console.module.css';
import insight from './Insight.module.css';
import { StyledDiv } from '@/components/ui/Styled';

// Funnels (W49, W9F): each step as a bar from zero, its share as text, and the change in points from the step
// before. The biggest drop is hatched and named in words, so no colour carries it. A group under 10 reads
// "fewer than 10" and has no bar. The split by channel sits beside the steps, and the funnel exports as CSV.

const SUPPRESSED = 'fewer than 10';

// The change in points from the step before, or null where either step is not shown.
function changes(steps: readonly FunnelStep[]): (number | null)[] {
  return steps.map((step, index) => {
    const before = steps[index - 1];
    if (before === undefined || before.suppressed || before.pct === null || step.suppressed || step.pct === null) {
      return null;
    }
    return before.pct - step.pct;
  });
}

function signed(points: number): string {
  if (points === 0) return '0';
  return points > 0 ? `−${points}` : `+${-points}`;
}

function csvCell(value: string): string {
  return `"${value.replace(/"/g, '""')}"`;
}

// The steps and the split as CSV, a suppressed figure written as "fewer than 10", as the page shows it.
function funnelCsv(funnel: Funnel): string {
  const rows: string[][] = [['Step', 'Share (%)', 'Count']];
  for (const step of funnel.steps) {
    rows.push(
      step.suppressed || step.pct === null
        ? [step.name, SUPPRESSED, SUPPRESSED]
        : [step.name, String(step.pct), String(step.count ?? '')],
    );
  }
  rows.push([]);
  rows.push(['Channel', 'Share (%)']);
  for (const row of funnel.split) {
    rows.push([row.channel, row.suppressed || row.pct === null ? SUPPRESSED : String(row.pct)]);
  }
  return `${rows.map((row) => row.map(csvCell).join(',')).join('\r\n')}\r\n`;
}

function exportCsv(funnel: Funnel) {
  const url = URL.createObjectURL(new Blob([funnelCsv(funnel)], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `${funnel.name}.csv`;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function FunnelsTab({ funnel }: { funnel: Funnel | null }) {
  if (funnel === null) return <p className={styles.help}>No funnel data for this range.</p>;
  const drop = biggestDrop(funnel.steps);
  const deltas = changes(funnel.steps);

  return (
    <div className={insight.funnelLayout}>
      <section className={insight.panel} aria-labelledby="funnel-heading">
        <h2 id="funnel-heading" className={insight.eyebrow}>
          {funnel.label}
        </h2>
        <p className={styles.help}>Share of those invited who reach each step.</p>
        <ol aria-label="Funnel steps" className={insight.steps}>
          {funnel.steps.map((step, index) => {
            const biggest = drop !== null && step.name === drop.to;
            const delta = deltas[index];
            return (
              <li key={step.name} className={biggest ? insight.stepBiggest : insight.step}>
                <span className={insight.stepName}>{step.name}</span>
                {step.suppressed || step.pct === null ? (
                  <span className={insight.suppressed}>{SUPPRESSED}</span>
                ) : (
                  <>
                    <StyledDiv
                      data-bar
                      data-drop={biggest ? '' : undefined}
                      aria-hidden="true"
                      className={biggest ? `${insight.bar} ${insight.hatched}` : insight.bar}
                      css={{ width: `${step.pct}%` }}
                    />
                    <span className={insight.pct}>{step.pct}%</span>
                  </>
                )}
                {step.suppressed || step.pct === null ? null : (
                  <span className={biggest ? insight.deltaBiggest : insight.delta}>
                    {delta === null ? '' : signed(delta)}
                    {biggest ? ' biggest' : ''}
                  </span>
                )}
              </li>
            );
          })}
        </ol>
      </section>
      <div className={insight.side}>
        {drop !== null && (
          <section className={insight.dropCard} aria-label="Biggest drop">
            <p className={`${insight.eyebrow} ${insight.dropEyebrow}`}>Biggest drop</p>
            <p>
              {drop.from} to {drop.to}: {drop.points} points.
            </p>
            {drop.exitElementId !== undefined && (
              <p>
                Exit element: <code>{drop.exitElementId}</code>.
              </p>
            )}
            {drop.medianSeconds !== undefined && <p>Median time between steps: {drop.medianSeconds} s.</p>}
          </section>
        )}
        <section className={insight.panel} aria-labelledby="split-heading">
          <h3 id="split-heading" className={insight.eyebrow}>
            Split: how they came in
          </h3>
          <div className={insight.scroll}>
            <table className={styles.table} aria-label="Funnel by channel">
              <thead>
                <tr>
                  <th scope="col">Split</th>
                  <th scope="col">Conversion</th>
                </tr>
              </thead>
              <tbody>
                {funnel.split.map((row) => (
                  <tr key={row.channel}>
                    <td>{row.channel}</td>
                    <td>{row.suppressed || row.pct === null ? SUPPRESSED : `${row.pct}%`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        <div className={insight.actions}>
          <button type="button" className={insight.button} onClick={() => exportCsv(funnel)}>
            Export CSV
          </button>
        </div>
      </div>
    </div>
  );
}
