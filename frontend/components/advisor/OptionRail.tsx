import { ShapeIcon, STATUS_LABELS, STATUS_SHAPES } from '@/components/ui/StatusBadge';
import type { OptionView } from '@/lib/advisor/options';
import styles from './OptionRail.module.css';

// The other options of the case, folded to the side while one option has the stage (the Call board, step 4).
// Same order as the options list, no rank. A network service is left out: it never has a booking. Folded, the
// rail is `inert` and hidden from assistive technology, so Tab never lands in something nobody can see.

export type OptionRailProps = {
  options: readonly OptionView[];
  /** The option on the stage: not repeated here. */
  currentServiceId: string;
  onOpen: (serviceId: string) => void;
  folded?: boolean;
};

function detail(option: OptionView): string {
  const word = STATUS_LABELS[option.status];
  if (option.status === 'over-capacity' && option.overBy !== null) return `${word} · +${option.overBy}`;
  if (option.effectiveAvailable !== null) {
    return `${word} · ${[String(option.effectiveAvailable), option.unitLabel].filter((part) => part !== null && part !== '').join(' ')}`;
  }
  return word;
}

export function OptionRail({ options, currentServiceId, onOpen, folded = false }: OptionRailProps) {
  const others = options.filter((option) => option.serviceId !== currentServiceId && option.network === null);
  return (
    <aside className={styles.rail} aria-label="Other options" inert={folded} aria-hidden={folded ? 'true' : undefined} data-el="ADV-OPT-RAIL">
      <h2 className={styles.heading}>Other options</h2>
      {others.length === 0 ? (
        <p className={styles.empty}>No other options for this patient.</p>
      ) : (
        <ul className={styles.list}>
          {others.map((option) => (
            <li key={option.serviceId}>
              <button type="button" className={styles.item} data-status={option.status} onClick={() => onOpen(option.serviceId)}>
                <span className={styles.name}>{option.name}</span>
                <span className={styles.detail}>
                  <ShapeIcon shape={STATUS_SHAPES[option.status]} />
                  {detail(option)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
