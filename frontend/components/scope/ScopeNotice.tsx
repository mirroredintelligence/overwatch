import type { ReactNode } from 'react';
import { Banner, type BannerProps } from '@/components/ui/Banner';

// A scope notice: a service stopped sharing, an organisation's updates are delayed, the wall fell back to
// its own board (docs/design/network-ui.md section 5). The existing tones only: info, warning, offline.
export function ScopeNotice({ tone, title, children }: { tone: BannerProps['tone']; title: string; children?: ReactNode }) {
  return (
    <Banner tone={tone} title={title} dataEl="SCOPE-BANNER-NOTICE">
      {children}
    </Banner>
  );
}
