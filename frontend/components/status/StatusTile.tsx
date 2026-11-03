import type { ReactNode } from 'react';
import { STATUS_LABELS } from '@/components/ui/StatusBadge';
import { StatusTag, type StatusTagVariant } from '@/components/ui/StatusTag';
import styles from './StatusTile.module.css';

// The large tile on every board. The chip is the foundation StatusTag (shape plus word); the words are the seven
// status-badge words, unchanged. A not-updated tile is dashed and an over-capacity tile has a hatched band.

export type TileStatus = 'accepting' | 'limited' | 'not-accepting' | 'over-capacity' | 'not-updated';

const VARIANT: Record<TileStatus, StatusTagVariant> = {
  accepting: 'live',
  limited: 'waiting',
  'not-accepting': 'closed',
  'over-capacity': 'over',
  'not-updated': 'todo',
};

export interface StatusTileProps {
  name: string;
  organisation?: string;
  status: TileStatus;
  // The big number as the board shows it: "4", "+2", or "?" when the figure is not known.
  figure: string;
  figureLabel: string;
  // "Updated 4 minutes ago", or the stale time for a not-updated tile.
  updated: string;
  // The user's own organisation (the board's "Your organisation" mark).
  own?: boolean;
  // Anything under the figure, such as a service line link.
  children?: ReactNode;
}

export function StatusTile({ name, organisation, status, figure, figureLabel, updated, own = false, children }: StatusTileProps) {
  const notUpdated = status === 'not-updated';
  const over = status === 'over-capacity';
  return (
    <div
      className={`${styles.tile}${notUpdated ? ` ${styles.notUpdated}` : ''}`}
      data-status={status}
    >
      {over && <span className={styles.over} aria-hidden="true" />}
      <div className={styles.head}>
        <h3 className={styles.name}>{name}</h3>
        {own && <span className={styles.own}>Your organisation</span>}
      </div>
      {organisation && <div className={styles.org}>{organisation}</div>}
      <div>
        <StatusTag variant={VARIANT[status]}>{STATUS_LABELS[status]}</StatusTag>
      </div>
      <div className={styles.figureRow}>
        <span className={styles.figure}>{figure}</span>
        <span className={styles.figureLabel}>{figureLabel}</span>
      </div>
      <div className={styles.updated}>{updated}</div>
      {children && <div className={styles.extra}>{children}</div>}
    </div>
  );
}
