// Red-phase stub for the root layout (retrofitted red proof for the smoke e2e test).
import type { ReactNode } from 'react';

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html>
      <body>{children}</body>
    </html>
  );
}
