import type { Metadata } from 'next';
import { BoardCounts } from '@/components/advisor/BoardCounts';
import { CallStage } from '@/components/advisor/CallStage';
import { StartCallButton } from '@/components/advisor/StartCallButton';
import { OwnScopeHeader } from '@/components/scope/OwnScopeHeader';
import styles from './page.module.css';

export const metadata: Metadata = {
  title: 'Advisor home · Overwatch',
};

// The advisor's home (URL /advisor). The route group (advisor) adds no segment, so this file is
// the page at /advisor, and the proxy guard (lib/auth/access.ts) already limits it to advisors.
// The overview of a call (boards/advisor/Call.dc.html, step 1): the board stripe above, and the
// call grid under it with the start button in the stage and the open cases alongside.
export default function AdvisorHomePage() {
  return (
    <main>
      {/* Which board the counts are of, and the way to the network's counts (WB11, W10-K3). */}
      <OwnScopeHeader ownHref="/advisor" networkHref="/network/home" />
      <section aria-labelledby="advisor-board-now" className={styles.board}>
        <h2 id="advisor-board-now" className={styles.visuallyHidden}>
          Board right now
        </h2>
        <BoardCounts />
        <p className={styles.boardLink}>
          <a href="/advisor/board">Open the wall board view</a>
        </p>
      </section>
      <CallStage
        step="overview"
        side={
          <section aria-labelledby="advisor-open-cases" className={styles.card}>
            <h2 id="advisor-open-cases" className={styles.kicker}>
              Open cases
            </h2>
            <p className={styles.body}>No open cases. Nothing from earlier calls is shown here.</p>
          </section>
        }
      >
        <div className={styles.stage}>
          <h1 className={styles.heading}>Ready for calls</h1>
          <p className={styles.lead}>The board above is live. When a call starts, it folds into a strip and the call takes the room.</p>
          <StartCallButton />
        </div>
      </CallStage>
    </main>
  );
}
