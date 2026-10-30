import type { Metadata } from 'next';
import { BoardCounts } from '@/components/advisor/BoardCounts';
import { StartCallButton } from '@/components/advisor/StartCallButton';

export const metadata: Metadata = {
  title: 'Advisor home · DIUCS capacity',
};

// The advisor's home (URL /advisor). The route group (advisor) adds no segment, so this file is
// the page at /advisor, and the proxy guard (lib/auth/access.ts) already limits it to advisors.
export default function AdvisorHomePage() {
  return (
    <main>
      <h1>Ready for calls</h1>
      <p>Advisor home</p>
      <StartCallButton />
      <section aria-labelledby="advisor-board-now">
        <h2 id="advisor-board-now">Board right now</h2>
        <BoardCounts />
        <p>
          <a href="/advisor/board">Open the wall board view</a>
        </p>
      </section>
      <p>No open cases. Nothing from earlier calls is shown here.</p>
    </main>
  );
}
