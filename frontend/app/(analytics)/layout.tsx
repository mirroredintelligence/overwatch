import type { ReactNode } from 'react';
import { StaffShell } from '@/app/StaffShell';

// The staff header and page frame around the analytics pages (components/shell).
export default function Layout({ children }: { children: ReactNode }) {
  return <StaffShell>{children}</StaffShell>;
}
