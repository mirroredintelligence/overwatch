import styles from './StatusBadge.module.css';

export type StatusCode =
  | 'accepting'
  | 'limited'
  | 'not-accepting'
  | 'over-capacity'
  | 'not-updated'
  | 'out-of-hours'
  | 'last-known';

export const STATUS_LABELS: Record<StatusCode, string> = {
  accepting: 'Accepting',
  limited: 'Limited',
  'not-accepting': 'Not accepting',
  'over-capacity': 'Over capacity',
  'not-updated': 'Not updated',
  'out-of-hours': 'Out of hours',
  'last-known': 'Last known',
};

export type Shape = 'circle-tick' | 'triangle' | 'circle-bar' | 'diamond' | 'dashed-circle' | 'moon';

// Not updated and last known share a shape on purpose: both mean "do not rely
// on this figure", and the word tells them apart.
export const STATUS_SHAPES: Record<StatusCode, Shape> = {
  accepting: 'circle-tick',
  limited: 'triangle',
  'not-accepting': 'circle-bar',
  'over-capacity': 'diamond',
  'not-updated': 'dashed-circle',
  'out-of-hours': 'moon',
  'last-known': 'dashed-circle',
};

// Icons draw in currentColor, so they follow the chip's text colour.
export function ShapeIcon({ shape }: { shape: Shape }) {
  const common = {
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 2,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': 'true' as const,
    focusable: 'false' as const,
    className: styles.icon,
  };
  switch (shape) {
    case 'circle-tick':
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="9" />
          <path d="M8 12.5l2.5 2.5L16 9.5" />
        </svg>
      );
    case 'triangle':
      return (
        <svg {...common}>
          <path d="M12 3.5L21.5 20h-19z" />
          <path d="M12 9.5v4.5" />
          <path d="M12 16.8v.1" />
        </svg>
      );
    case 'circle-bar':
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="9" />
          <path d="M7.5 12h9" />
        </svg>
      );
    case 'diamond':
      return (
        <svg {...common}>
          <path d="M12 2.5L21.5 12 12 21.5 2.5 12z" />
          <path d="M12 8.5v7" />
          <path d="M8.5 12h7" />
        </svg>
      );
    case 'dashed-circle':
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="9" strokeDasharray="3 2.5" />
          <path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 .9-1 1.7v.3" />
          <path d="M12 16.8v.1" />
        </svg>
      );
    case 'moon':
      return (
        <svg {...common}>
          <path d="M19.5 14.5A8 8 0 0 1 9.5 4.5a8 8 0 1 0 10 10z" />
        </svg>
      );
  }
}

export function StatusBadge({ status, size = 'sm' }: { status: StatusCode; size?: 'sm' | 'lg' }) {
  return (
    <span
      className={`${styles.badge} ${styles[status]} ${styles[size]}`}
      data-status={status}
      data-shape={STATUS_SHAPES[status]}
      data-size={size}
    >
      <ShapeIcon shape={STATUS_SHAPES[status]} />
      <span>{STATUS_LABELS[status]}</span>
    </span>
  );
}
