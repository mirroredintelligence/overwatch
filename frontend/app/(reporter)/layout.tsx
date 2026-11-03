import type { ReactNode } from 'react';

// No staff header here. The installed app's pages (/app/*) get their frame from app/(reporter)/app/layout.tsx,
// and the set-up pages (/setup/*) mount their own ProviderShell.
export default function Layout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
