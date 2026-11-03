import type { ReactNode } from 'react';

// The learn pages are public and draw their own frame (the head, the page ground and the phone bottom bar:
// components/learn/LearnLibrary), so there is no staff shell around them.
export default function Layout({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
