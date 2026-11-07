import type { ReactNode } from 'react';

// No staff header here: the page a printed QR code opens has no session (the code and a texted code are the credential),
// and mounts LinkFrame itself.
export default function Layout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
