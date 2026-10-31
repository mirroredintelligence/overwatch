import type { ReactNode } from 'react';
import { StaffShell } from '@/app/StaffShell';

// The header and page frame around the pages reached from a text or email link. There is no session on
// them (the link is the credential), so the header is the logo and Help only (components/shell).
export default function Layout({ children }: { children: ReactNode }) {
  return <StaffShell>{children}</StaffShell>;
}
