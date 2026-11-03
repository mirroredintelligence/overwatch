import { useId } from 'react';
import { districtsOf, type ServiceValues } from '@/lib/lead/serviceForm';
import { CADENCES } from './StepReporting';
import { ACCEPTS, EXCLUDES } from './StepCriteria';
import { CATEGORIES, MEASURES, StepFrame, labelOf } from './StepService';
import styles from './StepCheck.module.css';

// Step 4 of "Add a service", "Check, then add it" (boards/lead/AddService.dc.html): what was entered as three
// summary cards, each with Change (back to its step), the warning that advisors see the criteria at once, Back and
// the one primary button. The step holds no state; the page checks the form and posts it.

export type StepCheckProps = {
  values: ServiceValues;
  /** Change was pressed on a card: the step (from 0) it summarises. */
  onChange: (step: number) => void;
  onBack: () => void;
  onAdd: () => void;
  /** The service is being added: the button waits. */
  busy?: boolean;
  /** Why the service could not be added, in words. */
  problem?: string;
};

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export const lower = (text: string) => (text === '' ? '' : `${text.charAt(0).toLowerCase()}${text.slice(1)}`);

/** An ISO date (2026-12-12) in words (12 Dec 2026); anything else as typed. */
export function dateWords(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  const month = match ? MONTHS[Number(match[2]) - 1] : undefined;
  return match && month ? `${Number(match[3])} ${month} ${match[1]}` : iso;
}

/** The needs accepted, in the order they were chosen. */
export const acceptedWords = (values: ServiceValues) => values.accepts.map((key) => labelOf(ACCEPTS, key)).join(', ');

/** "18+" or "18 to 65". */
export function ageWords(values: ServiceValues): string {
  const youngest = values.ageMin.trim();
  const oldest = values.ageMax.trim();
  return oldest === '' ? `${youngest}+` : `${youngest} to ${oldest}`;
}

function Summary({ title, change, onChange, value, detail }: { title: string; change: string; onChange: () => void; value: string; detail: string }) {
  const id = useId();
  return (
    <div role="group" aria-labelledby={id} className={styles.summary}>
      <h2 id={id} className={styles.k}>
        {title}
      </h2>
      <p className={styles.value}>{value}</p>
      <p className={styles.detail}>{detail}</p>
      <button type="button" className={styles.change} aria-label={change} onClick={onChange}>
        Change
      </button>
    </div>
  );
}

export function StepCheck({ values, onChange, onBack, onAdd, busy, problem }: StepCheckProps) {
  const serviceDetail = [
    labelOf(CATEGORIES, values.category),
    values.measure ? `Counts ${lower(labelOf(MEASURES, values.measure))}` : '',
    `${values.establishedCapacity.trim()} established, usually ${values.usualMin.trim()} to ${values.usualMax.trim()}`,
    `${values.availableFrom} to ${values.availableTo}`,
  ]
    .filter(Boolean)
    .join('. ');

  const reportDetail = [
    // Only the last four digits of a number are ever shown again, and an address not at all.
    values.channel === 'text' ? `Phone ending ${values.mobile.replace(/\D/g, '').slice(-4)}` : '',
    labelOf(CADENCES, values.cadence),
  ]
    .filter(Boolean)
    .join('. ');

  const refused = values.excludes.map((key) => lower(labelOf(EXCLUDES, key)));
  const takesDetail = [
    `Age ${ageWords(values)}`,
    districtsOf(values.districts).join(', '),
    refused.length > 0 ? `Not ${refused.join(' or ')}` : '',
    `Review by ${dateWords(values.reviewBy)}`,
  ]
    .filter(Boolean)
    .join('. ');

  return (
    <StepFrame title="Check, then add it" errors={[]} onNext={onAdd} onBack={onBack} nextLabel="Add the service" busy={busy} dataEl="LEAD-ADD-SAVE-BTN">
      <div className={styles.cards}>
        <Summary
          title="The service"
          change="Change the service"
          onChange={() => onChange(0)}
          value={values.name.trim()}
          detail={`${serviceDetail}.`}
        />
        <Summary
          title="Who reports"
          change="Change who reports"
          onChange={() => onChange(1)}
          value={`${values.roleName.trim()}, by ${values.channel}`}
          detail={`${reportDetail}.`}
        />
        <Summary
          title="Who it takes"
          change="Change who it takes"
          onChange={() => onChange(2)}
          value={acceptedWords(values)}
          detail={`${takesDetail}.`}
        />
      </div>
      <p className={styles.warning}>
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="9" />
          <path d="M12 8v5M12 16h.01" />
        </svg>
        <span>
          Advisors will see these criteria as soon as you add the service. They are reviewed by {dateWords(values.reviewBy)}.
        </span>
      </p>
      {problem ? (
        <p role="alert" className={styles.problem}>
          {problem}
        </p>
      ) : null}
    </StepFrame>
  );
}
