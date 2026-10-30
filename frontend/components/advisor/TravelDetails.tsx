import { Button } from '@/components/ui/Button';
import type { OptionView } from '@/lib/advisor/options';
import styles from './map.module.css';

// The travel estimate, leg by leg (W50). It is a range for the area, not a promise: the patient is
// placed at the postcode centre. A visiting service is included in its own response time.

const CAVEAT =
  'A range, not a promise. Roads, weather and the time of day change it. The patient is placed at the postcode centre, so the range is for the area, not the door.';
const VISITING = 'Included in their response time';
const NO_LEGS = 'No travel legs were recorded for this service.';

function rangeText(low: number, high: number): string {
  return low === high ? `${low} min` : `${low} to ${high} min`;
}

export function TravelDetails({ option, caseId }: { option: OptionView; caseId: string }) {
  const legs = option.travel?.legs ?? [];
  const visiting = option.coverage !== null;
  const report = `/help/problem?from=${encodeURIComponent(`/advisor/case/${caseId}/map`)}`;

  return (
    <div className={styles.details}>
      <table className={styles.table} aria-label="Travel details">
        <thead>
          <tr>
            <th scope="col">Leg</th>
            <th scope="col">Range</th>
            <th scope="col">How</th>
            <th scope="col">Source</th>
          </tr>
        </thead>
        <tbody>
          {legs.map((leg) => (
            <tr key={leg.label}>
              <th scope="row">{leg.label}</th>
              <td>{rangeText(leg.low, leg.high)}</td>
              <td>{leg.how}</td>
              <td>{leg.source}</td>
            </tr>
          ))}
          {visiting ? (
            <tr>
              <th scope="row">{`${option.name}, visiting`}</th>
              <td>{VISITING}</td>
              <td />
              <td />
            </tr>
          ) : null}
        </tbody>
      </table>
      {legs.length === 0 && !visiting ? <p className={styles.note}>{NO_LEGS}</p> : null}
      <p className={styles.note}>{CAVEAT}</p>
      <div className={styles.actions}>
        <Button variant="neutral" href={report} dataEl="ADV-MAP-REPORT-BTN">
          Report a wrong estimate
        </Button>
      </div>
    </div>
  );
}
