import type { ReactNode } from 'react';

// The register pages have no session and no staff header: each page draws its own RegisterStage
// (components/register), the frame with the checklist, or the phone shell on a small screen.
export default function Layout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
