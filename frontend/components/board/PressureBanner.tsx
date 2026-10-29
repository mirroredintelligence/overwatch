import { Banner } from '@/components/ui/Banner';
import type { Board } from '@/lib/board/types';

// "System under pressure" (ui-screens.md, artboard "BoardSurge"; domain-rules 1.7).
// The back end decides when it shows: `allLimitedOrWorse` is true when every service
// that is in hours is limited, not accepting or over capacity, and out-of-hours
// services are left out. The count is the number of services in hours, so it agrees
// with the tiles a person can see. Words carry the meaning; the warning colour only
// adds to them. It is shown for a current board only (the board decides, see Board).

const TITLE = 'System under pressure';
const WORSE = 'limited, not accepting or over capacity.';

export function PressureBanner({ board }: { board: Pick<Board, 'allLimitedOrWorse' | 'entries'> }) {
  if (!board.allLimitedOrWorse) return null;
  const inHours = board.entries.filter((e) => e.status !== 'out-of-hours').length;
  // A flag with no service in hours behind it cannot be put in words ("All 0 services").
  if (inHours === 0) return null;
  const text = inHours === 1 ? `The only service in hours is ${WORSE}` : `All ${inHours} services are ${WORSE}`;
  return (
    <Banner tone="warning" title={TITLE} dataEl="WALL-PRESSURE-BANNER">
      {text}
    </Banner>
  );
}
