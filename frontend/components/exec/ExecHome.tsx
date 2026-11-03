import Link from 'next/link';
import { Button } from '@/components/ui/Button';
import { StatusTag } from '@/components/ui/StatusTag';
import type { Board, BoardEntry } from '@/lib/board/types';
import { attentionLine, limitedOrWorse, needsAttention, pressureChip } from '@/lib/exec/homeSummary';
import { formatCount, formatPct } from '@/lib/exec/weekFormat';
import type { WeekSummary } from '@/lib/exec/weekSummary';
import { AttentionRail, PlanningStage, STATUS_TAG, statusWord } from './PlanningStage';
import styles from './Exec.module.css';
import home from './PlanningStage.module.css';

// The executive's home (W40; boards/planning/Morph.dc.html at its first stage, PH1 on a phone). The planning
// stage's home state: the five tiles, what needs attention, and the week at a glance beside it. Server-rendered:
// it holds no patient information and no state. The name is the organisation's (or the network's) from the
// board, never a constant. Opening a service is a link to its route, where the stage becomes the service.

function countsByStatus(board: Board): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const entry of board.entries) counts[entry.status] = (counts[entry.status] ?? 0) + 1;
  return counts;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** "17 to 23 Oct", or "28 Oct to 3 Nov" across a month end. */
function rangeText(from: string, to: string): string {
  const [, fromMonth, fromDay] = from.split('-');
  const [, toMonth, toDay] = to.split('-');
  const start = MONTHS[Number(fromMonth) - 1] ?? '';
  const end = MONTHS[Number(toMonth) - 1] ?? '';
  return start === end ? `${Number(fromDay)} to ${Number(toDay)} ${end}` : `${Number(fromDay)} ${start} to ${Number(toDay)} ${end}`;
}

function WeekGlance({ week }: { week: WeekSummary | null | undefined }) {
  return (
    <section className={home.card} aria-label="This week">
      <div className={home.eyebrow}>This week</div>
      {week ? (
        <>
          <p className={home.range}>{rangeText(week.from, week.to)}</p>
          <div className={home.figures}>
            <div>
              <div className={home.figure}>{formatCount(week.referrals)}</div>
              <div>referrals</div>
            </div>
            <div>
              <div className={home.figure}>{formatPct(week.onTimePct)}</div>
              <div>updates on time</div>
            </div>
          </div>
        </>
      ) : (
        <p className={home.range}>The figures for the week could not be read.</p>
      )}
      <Button variant="secondary" href="/planning/week">
        See the week
      </Button>
    </section>
  );
}

function AttentionRow({ entry, now }: { entry: BoardEntry; now: string }) {
  return (
    <li className={home.row} data-status={entry.status}>
      <div className={home.rowText}>
        <div className={home.rowName}>{entry.name}</div>
        <div className={home.rowLine}>{attentionLine(entry, now)}</div>
      </div>
      <StatusTag variant={STATUS_TAG[entry.status] ?? 'todo'}>{statusWord(entry.status)}</StatusTag>
      <Link
        href={`/planning/services/${encodeURIComponent(entry.serviceId)}`}
        className={home.open}
        aria-label={`Open ${entry.name}`}
      >
        Open
      </Link>
    </li>
  );
}

export function ExecHome({
  board,
  name,
  phoneAlerts = false,
  week,
}: {
  board: Board;
  name: string;
  phoneAlerts?: boolean;
  /** The last complete week, or null when it could not be read; left out, the glance says nothing of it. */
  week?: WeekSummary | null;
}) {
  const chip = pressureChip(board.pressure);
  const { limited, inHours } = limitedOrWorse(board);
  const attention: BoardEntry[] = needsAttention(board);

  const listWide = (
    <div className={styles.stack}>
      <header className={styles.stack}>
        <h1 className={styles.heading}>{name}</h1>
        <p data-el="EXEC-HOME-PRESSURE" aria-label={chip.label} className={styles.pressure}>
          <span className={styles.chipWord}>{chip.word}</span>
          <span>{`${limited} of ${inHours} services limited or worse`}</span>
        </p>
      </header>

      <section className={home.attention} aria-labelledby="exec-attention-heading">
        <h2 id="exec-attention-heading" className={home.attentionHeading}>{`Needs attention (${attention.length})`}</h2>
        {attention.length === 0 ? (
          <div className={home.empty}>
            <div className={home.emptyTitle}>Nothing needs attention</div>
            <div>{`All ${inHours} services reported in time, and none is not accepting or over capacity.`}</div>
          </div>
        ) : (
          <ul className={home.rows} aria-label={`Needs attention (${attention.length})`}>
            {attention.map((entry) => (
              <AttentionRow key={entry.serviceId} entry={entry} now={board.generatedAt} />
            ))}
          </ul>
        )}
      </section>

      <div className={styles.actions}>
        <Button variant="secondary" href="/planning/services" dataEl="EXEC-HOME-SEEALL-BTN">
          See all services
        </Button>
        <Button variant="secondary" href="/planning/flows" dataEl="EXEC-HOME-FLOWS-BTN">
          See planning flows
        </Button>
        <Button variant="secondary" href="/planning/coverage" dataEl="EXEC-HOME-COVERAGE-BTN">
          Where coverage runs out
        </Button>
        {phoneAlerts ? (
          <Button variant="secondary" href="/planning/phone" dataEl="EXEC-HOME-PHONE-BTN">
            Alerts on this phone
          </Button>
        ) : null}
      </div>
    </div>
  );

  return (
    <PlanningStage
      stage="home"
      counts={countsByStatus(board)}
      listWide={listWide}
      rail={<AttentionRail entries={attention} />}
      sideHome={<WeekGlance week={week} />}
    />
  );
}
