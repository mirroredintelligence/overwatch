import type { ReactNode } from 'react';
import { WorkspaceShell } from '@/app/WorkspaceShell';

// The advisor v2 route group's layout: its pages sit in the workspace shell (chat and canvas, DEC-1376).
export default function Layout({ children }: { children: ReactNode }) {
  return <WorkspaceShell>{children}</WorkspaceShell>;
}
