import type { ReactNode } from 'react';
import { ReporterAppFrame } from '@/components/reporter/parts';

// The installed app's frame (dark top bar, bottom tab bar where it belongs) around every /app page.
export default function Layout({ children }: { children: ReactNode }) {
  return <ReporterAppFrame>{children}</ReporterAppFrame>;
}
