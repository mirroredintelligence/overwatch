import { ServiceCard } from '@/components/advisor/ServiceCard';
import type { OptionView } from '@/lib/advisor/options';
import { lastReportedLine } from '@/lib/advisor/reporting';
import styles from './V2.module.css';

// A list of services as the v1 summary rows (ServiceCard, DEC-1343), each linking to the service's page. A late, old
// or unknown figure reads "Current capacity unavailable" in the row and the last figure is added small underneath;
// it is never a number to offer.

export function ServiceRows({ options, label }: { options: OptionView[]; label: string }) {
  return (
    <ul className={styles.rows} aria-label={label}>
      {options.map((option) => (
        <li key={option.serviceId}>
          <ServiceCard caseId="" option={option} variant="row" openHref={`/advisor/v2/services/${encodeURIComponent(option.serviceId)}`} />
          {option.figureUnavailable ? <p className={styles.small}>{lastReportedLine(option)}</p> : null}
        </li>
      ))}
    </ul>
  );
}
