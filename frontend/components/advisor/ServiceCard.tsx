import Link from 'next/link';
import { Button } from '@/components/ui/Button';
import { StatusBadge } from '@/components/ui/StatusBadge';
import type { OptionView } from '@/lib/advisor/options';
import { categoryLabel, durationText } from '@/lib/board/format';
import { NetworkServiceLine } from './NetworkServiceLine';
import { OptionBooking } from './OptionBooking';
import { ServicePhone } from './ServicePhone';
import styles from './ServiceCard.module.css';

// One service in the options list (W13). Order and content come from the back end: a card has no rank,
// no "best" label and no score. A network service is read only: it names its organisation and has no
// booking, phoned, declined or criteria action (network-ui.md section 9; its criteria are another
// organisation's, which the viewer's own criteria read would not find, KI-794): the one thing to do is phone it.
// Another service of the viewer's own
// organisation carries the booking panel of this case (W20): the request control, then the card it leaves.

export type ServiceCardProps = {
  caseId: string;
  option: OptionView;
  /** 'full' (default) is the whole card; 'row' is the summary line of the options list, opened by `openHref`. */
  variant?: 'full' | 'row';
  openHref?: string;
  /** The level of the name; the section headings follow one level down. */
  headingLevel?: 2 | 3;
  /** The Request state: "Back to options" beside the request control. */
  backToOptions?: boolean;
  /** Back to the options, and the clinical advisor, from the booking card. */
  onSeeOptions?: () => void;
  onAskClinical?: () => void;
  onCriteria?: (serviceId: string) => void;
  /** The criteria of ANOTHER organisation's service (the network pages' dialog). The own-service read cannot
   *  find them (KI-794), so a network card has the button only when this is given. */
  onNetworkCriteria?: (serviceId: string) => void;
  onPhoned?: (serviceId: string) => void;
  onDeclined?: (serviceId: string) => void;
};

const NOT_KNOWN = 'Not recorded';
const UNIT_UNKNOWN = 'Phone to confirm';

export function numberText(option: OptionView): string {
  if (option.status === 'over-capacity' && option.overBy !== null) return `+${option.overBy}`;
  if (option.effectiveAvailable !== null) return String(option.effectiveAvailable);
  return '?';
}

function dataAgeLine(option: OptionView): string {
  if (option.dataAgeSeconds === null) return 'Data age: not known';
  return `Data age: ${durationText(Math.floor(option.dataAgeSeconds / 60))} ago`;
}

// The line under a row's name: type, travel or response, and when the figure was reported.
function rowCaption(option: OptionView): string {
  const age = option.dataAgeSeconds === null ? 'update time not known' : `updated ${durationText(Math.floor(option.dataAgeSeconds / 60))} ago`;
  return [option.category === null ? null : categoryLabel(option.category), option.travelText, age].filter((part) => part !== null).join(' · ');
}

function ServiceRow({ option, openHref }: { option: OptionView; openHref?: string }) {
  const network = option.network;
  return (
    <article className={`${styles.row} ${option.status === 'over-capacity' ? styles.rowSurge : ''}`} aria-label={option.name} data-el="ADV-OPT-CARD">
      <div className={styles.rowBody}>
        <h3 className={styles.rowName}>{option.name}</h3>
        {network === null ? null : <p className={styles.caption}>{network.organisation}</p>}
        <p className={styles.rowCaption}>
          {rowCaption(option)}
          {option.staleWarning ? <> <span className={styles.old}>old</span></> : null}
        </p>
        <StatusBadge status={option.status} />
      </div>
      <div className={styles.rowFigure}>
        <p className={styles.rowNumber} data-el="ADV-OPT-NUMBER">
          {numberText(option)}
        </p>
        <p className={styles.rowUnit}>{option.unitLabel ?? UNIT_UNKNOWN}</p>
      </div>
      {openHref === undefined ? null : (
        <Link className={styles.open} href={openHref} scroll={false} aria-label={`Open ${option.name}`} data-el="ADV-OPT-OPEN-LINK">
          Open
        </Link>
      )}
    </article>
  );
}

export function ServiceCard({ caseId, option, variant = 'full', openHref, headingLevel = 3, backToOptions, onSeeOptions, onAskClinical, onCriteria, onNetworkCriteria, onPhoned, onDeclined }: ServiceCardProps) {
  if (variant === 'row') return <ServiceRow option={option} openHref={openHref} />;
  const Name = headingLevel === 2 ? 'h2' : 'h3';
  const Section = headingLevel === 2 ? 'h3' : 'h4';
  const network = option.network;
  const checks = option.staleWarning
    ? [...option.checks, 'Data is over 2 hrs old. Consider phoning.']
    : option.checks;

  return (
    <article className={styles.card} aria-label={option.name} data-el="ADV-OPT-CARD">
      <header className={styles.head}>
        <div className={styles.titles}>
          <Name className={styles.name}>{option.name}</Name>
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
      {network === null || network.source === '' ? null : <p className={styles.caption}>{network.source}</p>}
      {network === null ? null : <NetworkServiceLine option={option} className={styles.line} />}

      {option.fits.length === 0 ? null : (
        <section className={styles.section}>
          <Section className={styles.sectionHeading}>Why it fits</Section>
          <ul className={styles.list}>
            {option.fits.map((fit) => (
              <li key={fit}>{fit}</li>
            ))}
          </ul>
        </section>
      )}

      {checks.length === 0 ? null : (
        <section className={styles.section}>
          <Section className={styles.sectionHeading}>Check before offering</Section>
          <ul className={styles.list}>
            {checks.map((check) => (
              <li key={check}>{check}</li>
            ))}
          </ul>
        </section>
      )}

      {network === null ? <ServicePhone phone={option.phone} /> : null}

      {network === null ? (
        <OptionBooking caseId={caseId} option={option} onSeeOptions={onSeeOptions} onAskClinical={onAskClinical} backToOptions={backToOptions} />
      ) : null}

      <div className={styles.actions}>
        {network === null ? (
          <Button variant="secondary" dataEl="ADV-OPT-CRITERIA-BTN" onClick={() => onCriteria?.(option.serviceId)}>
            Criteria
          </Button>
        ) : onNetworkCriteria === undefined ? null : (
          <Button variant="secondary" dataEl="ADV-OPT-CRITERIA-BTN" onClick={() => onNetworkCriteria(option.serviceId)}>
            Criteria
          </Button>
        )}
        {network === null ? (
          <Button variant="secondary" dataEl="ADV-OPT-PHONED-BTN" onClick={() => onPhoned?.(option.serviceId)}>
            I phoned
          </Button>
        ) : null}
        {network === null ? (
          <Button variant="secondary" dataEl="ADV-OPT-DECLINED-BTN" onClick={() => onDeclined?.(option.serviceId)}>
            They declined
          </Button>
        ) : null}
      </div>
    </article>
  );
}
