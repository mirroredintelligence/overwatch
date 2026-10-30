import { AGE_BANDS, type AgeCode, labelOf, NEEDS, type NeedCode, URGENCIES, type UrgencyCode } from '@/lib/advisor/codes';
import styles from './CaseSummaryLine.module.css';

// One line that says what the case is, for the screens after the needs form (W11):
// "80+ · DT4 8XX · Fall, Frailty · Within 2 hrs", with an Edit link back to the needs form.

export type CaseSummaryLineProps = {
  caseId: string;
  ageBand: AgeCode | null;
  postcode: string | null;
  needs: NeedCode[];
  urgency: UrgencyCode | null;
};

function needShort(code: NeedCode): string {
  return NEEDS.find((need) => need.code === code)?.short ?? code;
}

export function CaseSummaryLine({ caseId, ageBand, postcode, needs, urgency }: CaseSummaryLineProps) {
  const parts = [
    labelOf(AGE_BANDS, ageBand),
    postcode,
    needs.length > 0 ? needs.map(needShort).join(', ') : null,
    labelOf(URGENCIES, urgency),
  ].filter((part): part is string => part !== null && part !== '');

  return (
    <div className={styles.line}>
      <p className={styles.text} data-el="ADV-CASE-SUMMARY">
        {parts.join(' · ')}
      </p>
      <a className={styles.edit} href={`/advisor/case/${encodeURIComponent(caseId)}`} data-el="ADV-CASE-SUMMARY-EDIT">
        Edit
      </a>
    </div>
  );
}
