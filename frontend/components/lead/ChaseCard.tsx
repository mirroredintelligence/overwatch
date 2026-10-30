import type { ChaseItem } from '@/lib/lead/types';

// Red stub (DEC-010).
export type ChaseCardProps = { item: ChaseItem; onEnterPhoned: () => void; onRemind: () => void };
export function ChaseCard(props: ChaseCardProps) {
  void props;
  return null;
}
