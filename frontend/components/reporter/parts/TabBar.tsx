import type { ReactNode } from 'react';
import { itemIsCurrent, type FrameItem } from '@/components/shell/frame';
import styles from './TabBar.module.css';

// The installed app's bottom bar (artboards B6, B9): Update, Services, Settings, Help, a picture over each
// word. The current tab is marked with aria-current and is also drawn bold with a bar above it, so it is not
// told apart by colour alone. "Update" is the front door (/app, which redirects to the right update screen)
// and stands for every update page.

type Tab = FrameItem & { readonly picture: ReactNode };

const TABS: readonly Tab[] = [
  {
    label: 'Update',
    href: '/app',
    icon: 'checklist',
    exact: true,
    alsoMatch: ['/app/update', '/app/respond', '/app/booking'],
    picture: <path d="M4 12.5l5 5L20 6.5" />,
  },
  {
    label: 'Services',
    href: '/app/services',
    icon: 'board',
    picture: (
      <>
        <rect x="3" y="3" width="7" height="7" rx="1.5" />
        <rect x="14" y="3" width="7" height="7" rx="1.5" />
        <rect x="3" y="14" width="7" height="7" rx="1.5" />
        <rect x="14" y="14" width="7" height="7" rx="1.5" />
      </>
    ),
  },
  {
    label: 'Settings',
    href: '/app/settings',
    icon: 'sliders',
    picture: (
      <>
        <path d="M4 7h10M18 7h2M4 17h2M10 17h10" />
        <circle cx="16" cy="7" r="2" />
        <circle cx="8" cy="17" r="2" />
      </>
    ),
  },
  {
    label: 'Help',
    href: '/help',
    icon: 'help',
    picture: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .9-1 1.7M12 17h.01" />
      </>
    ),
  },
];

export function TabBar({ pathname }: { pathname: string }) {
  return (
    <nav className={styles.bar} aria-label="App">
      {TABS.map((tab) => (
        <a key={tab.href} className={styles.tab} href={tab.href} aria-current={itemIsCurrent(pathname, tab) ? 'page' : undefined}>
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
            {tab.picture}
          </svg>
          <span>{tab.label}</span>
        </a>
      ))}
    </nav>
  );
}
