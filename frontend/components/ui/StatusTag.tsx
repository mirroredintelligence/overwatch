import type { ReactNode } from 'react';
import styles from './StatusTag.module.css';

// Status as shape plus word, never colour alone (design canvas "Shared building blocks"). The shape is
// decoration (aria-hidden); the word the page passes carries the meaning, so write it as the status.
//
//   done      filled circle, primary          waiting   half circle, amber
//   todo      dashed circle, muted            problem   triangle, purple
//   live      filled, primary                 closed    box with a cross
//   over      triangle, purple                paused    dashed square
//   confirmed circle with a tick, primary     due       clock face, amber

export type StatusTagVariant = 'done' | 'waiting' | 'todo' | 'problem' | 'live' | 'closed' | 'over' | 'paused' | 'confirmed' | 'due';

function Shape({ variant }: { variant: StatusTagVariant }) {
  const common = { width: 14, height: 14, viewBox: '0 0 16 16', 'aria-hidden': true, focusable: false } as const;
  switch (variant) {
    case 'done':
    case 'live':
      return (
        <svg {...common}>
          <circle cx="8" cy="8" r="7" fill="currentColor" />
        </svg>
      );
    case 'waiting':
      return (
        <svg {...common}>
          <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="2" />
          <path d="M8 2a6 6 0 0 0 0 12z" fill="currentColor" />
        </svg>
      );
    case 'todo':
      return (
        <svg {...common}>
          <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="2" strokeDasharray="3 2.4" />
        </svg>
      );
    case 'problem':
    case 'over':
      return (
        <svg {...common}>
          <path d="M8 1.5L15 14H1z" fill="currentColor" strokeLinejoin="round" stroke="currentColor" strokeWidth="1" />
        </svg>
      );
    case 'closed':
      return (
        <svg {...common}>
          <rect x="1.5" y="1.5" width="13" height="13" rx="2" fill="none" stroke="currentColor" strokeWidth="2" />
          <path d="M5 5l6 6M11 5l-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
      );
    case 'confirmed':
      return (
        <svg {...common}>
          <circle cx="8" cy="8" r="7" fill="currentColor" />
          <path d="M4.6 8.3l2.2 2.2 4.6-4.7" fill="none" stroke="Canvas" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case 'due':
      return (
        <svg {...common}>
          <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="2" />
          <path d="M8 4.6V8l2.4 1.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case 'paused':
      return (
        <svg {...common}>
          <rect x="2" y="2" width="12" height="12" rx="2" fill="none" stroke="currentColor" strokeWidth="2" strokeDasharray="3 2.4" />
        </svg>
      );
  }
}

export function StatusTag({ variant, children }: { variant: StatusTagVariant; children: ReactNode }) {
  return (
    <span className={`${styles.tag} ${styles[variant]}`} data-variant={variant}>
      <Shape variant={variant} />
      <span>{children}</span>
    </span>
  );
}
