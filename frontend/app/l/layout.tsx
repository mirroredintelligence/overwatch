import type { ReactNode } from 'react';

// No staff header here: the pages reached from a text or email link have no session (the link is the
// credential), and each mounts LinkFrame itself.
export default function Layout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
