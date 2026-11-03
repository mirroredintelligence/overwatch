import type { ReactNode } from 'react';

// The pages reached from a text or email link. There is no session on them (the link is the credential)
// and no staff header: each page draws its own ProviderShell (components/provider).
export default function Layout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
