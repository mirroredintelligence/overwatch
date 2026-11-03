import { AGE_BANDS, type AgeCode, labelOf, NEEDS, type NeedCode, URGENCIES, type UrgencyCode } from '@/lib/advisor/codes';
import type { Score } from '@/lib/advisor/scores';
import { scoreText } from '@/lib/advisor/summary';
import styles from './CaseSummaryLine.module.css';

// The pinned patient card of a call (W11, Call board): "80+ · DT4 8XX" large, a chip for each need and the
// urgency, the scores the referrer gave, and an Edit needs link back to the needs form. No name, ever.

export type CaseSummaryLineProps = {
  caseId: string;
  ageBand: AgeCode | null;
  postcode: string | null;
  needs: NeedCode[];
  urgency: UrgencyCode | null;
  scores?: Score[];
};

function needLabel(code: NeedCode): string {
  return NEEDS.find((need) => need.code === code)?.label ?? code;
}

export function CaseSummaryLine({ caseId, ageBand, postcode, needs, urgency, scores = [] }: CaseSummaryLineProps) {
  const headline = [labelOf(AGE_BANDS, ageBand), postcode].filter((part): part is string => part !== null && part !== '').join(' · ');
  const chips = [...needs.map(needLabel), labelOf(URGENCIES, urgency)].filter((chip): chip is string => chip !== null && chip !== '');

  return (
    <section className={styles.card} aria-label="This patient" data-el="ADV-CASE-SUMMARY">
      <p className={styles.kicker} aria-hidden="true">
        This patient
      </p>
      {headline !== '' ? <p className={styles.headline}>{headline}</p> : null}
      {chips.length > 0 ? (
        <ul className={styles.chips} aria-label="Needs and urgency">
          {chips.map((chip) => (
            <li key={chip} className={styles.chip}>
              {chip}
            </li>
          ))}
        </ul>
      ) : null}
      {scores.length > 0 ? <p className={styles.scores}>{scores.map(scoreText).join(' · ')}</p> : null}
      <a className={styles.edit} href={`/advisor/case/${encodeURIComponent(caseId)}`} data-el="ADV-CASE-SUMMARY-EDIT">
        Edit needs
      </a>
    </section>
  );
}
