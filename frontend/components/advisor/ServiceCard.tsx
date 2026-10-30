import { Button } from '@/components/ui/Button';
import { StatusBadge } from '@/components/ui/StatusBadge';
import type { OptionView } from '@/lib/advisor/options';
import { categoryLabel, durationText } from '@/lib/board/format';
import styles from './ServiceCard.module.css';

// One service in the options list (W13). Order and content come from the back end: a card has no rank,
// no "best" label and no score. A network service is read only: it names its organisation and has no
// booking, phoned or declined action (network-ui.md section 9).

export type ServiceCardProps = {
  option: OptionView;
  onRequest?: (serviceId: string) => void;
  onCriteria?: (serviceId: string) => void;
  onPhoned?: (serviceId: string) => void;
};

const NOT_KNOWN = 'Not recorded';
const UNIT_UNKNOWN = 'Phone to confirm';

function numberText(option: OptionView): string {
  if (option.status === 'over-capacity' && option.overBy !== null) return `+${option.overBy}`;
  if (option.effectiveAvailable !== null) return String(option.effectiveAvailable);
  return '?';
}

function dataAgeLine(option: OptionView): string {
  if (option.dataAgeSeconds === null) return 'Data age: not known';
  return `Data age: ${durationText(Math.floor(option.dataAgeSeconds / 60))} ago`;
}

export function ServiceCard({ option, onRequest, onCriteria, onPhoned }: ServiceCardProps) {
  const network = option.network;
  const checks = option.staleWarning
    ? [...option.checks, 'Data is over 2 hrs old. Consider phoning.']
    : option.checks;

  return (
    <article className={styles.card} aria-label={option.name} data-el="ADV-OPT-CARD">
      <header className={styles.head}>
        <div className={styles.titles}>
          <h3 className={styles.name}>{option.name}</h3>
          {option.category === null ? null : <p className={styles.caption}>{categoryLabel(option.category)}</p>}
          {network === null ? null : <p className={styles.caption}>{network.organisation}</p>}
        </div>
        <StatusBadge status={option.status} />
      </header>

      <div className={styles.figure}>
        <p className={styles.number} data-el="ADV-OPT-NUMBER">
          {numberText(option)}
        </p>
        <p className={styles.unit}>{option.unitLabel ?? UNIT_UNKNOWN}</p>
      </div>

      <p className={styles.line}>{`Response or travel: ${option.travelText ?? NOT_KNOWN}`}</p>
      <p className={styles.line}>{dataAgeLine(option)}</p>
      {network === null ? null : <p className={styles.caption}>{network.source}</p>}

      {option.fits.length === 0 ? null : (
        <section className={styles.section}>
          <h4 className={styles.sectionHeading}>Why it fits</h4>
          <ul className={styles.list}>
            {option.fits.map((fit) => (
              <li key={fit}>{fit}</li>
            ))}
          </ul>
        </section>
      )}

      {checks.length === 0 ? null : (
        <section className={styles.section}>
          <h4 className={styles.sectionHeading}>Check before offering</h4>
          <ul className={styles.list}>
            {checks.map((check) => (
              <li key={check}>{check}</li>
            ))}
          </ul>
        </section>
      )}

      <div className={styles.actions}>
        {network === null ? (
          <Button variant="primary" dataEl="ADV-OPT-REQUEST-BTN" onClick={() => onRequest?.(option.serviceId)}>
            Request booking
          </Button>
        ) : null}
        <Button variant="secondary" dataEl="ADV-OPT-CRITERIA-BTN" onClick={() => onCriteria?.(option.serviceId)}>
          Criteria
        </Button>
        {network === null ? (
          <Button variant="secondary" dataEl="ADV-OPT-PHONED-BTN" onClick={() => onPhoned?.(option.serviceId)}>
            I phoned
          </Button>
        ) : null}
      </div>
    </article>
  );
}
