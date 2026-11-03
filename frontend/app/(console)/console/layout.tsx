import type { ReactNode } from 'react';
import { AppFrame } from '@/components/shell/AppFrame';
import type { FrameItem } from '@/components/shell/frame';

// The support console's frame (DEC-1326): the shared rail and top bar around every console page. The pages keep
// their own access check (a support session only); this layout draws no heading and no main, as the frame never does.

const ITEMS: readonly FrameItem[] = [
  { label: 'Sessions', href: '/console', icon: 'list', exact: true, alsoMatch: ['/console/session', '/console/trace'] },
  { label: 'Insight', href: '/console/insight', icon: 'chart' },
];

export default function ConsoleLayout({ children }: { children: ReactNode }) {
  return (
    <AppFrame portal="operator" items={ITEMS} organisation="Support console" role="support" roleWords={{ support: 'Support' }}>
      {children}
    </AppFrame>
  );
}
