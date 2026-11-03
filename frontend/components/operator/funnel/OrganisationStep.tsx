'use client';

import { organisationTypeWord } from '@/lib/operator/words';
import { whenText } from '@/lib/tenantAdmin/words';
import styles from '@/components/admin/admin.module.css';
import ts from '../Tenant.module.css';
import { StepSection, type PanelProps } from './shared';

const COUNTRY_WORD: Record<string, string> = { GB: 'United Kingdom', IE: 'Ireland' };

/** Step 1. The organisation as the NHS record gave it. Nothing here is written: the record is read-only once created. */
export function OrganisationStep(props: PanelProps) {
  const t = props.detail.tenant;
  return (
    <StepSection
      step={props.step}
      heading={props.heading}
      details={
        <dl className={styles.facts}>
          <dt>Organisation id</dt>
          <dd>{t.id}</dd>
          <dt>ODS code</dt>
          <dd>{t.odsCode ?? '-'}</dd>
          <dt>Created</dt>
          <dd>{whenText(t.createdAt)}</dd>
        </dl>
      }
    >
      <p className={ts.text}>Check these are right. They came from the NHS record when the organisation was created, and cannot be changed here.</p>
      <dl className={styles.facts}>
        <dt>Name</dt>
        <dd>{t.displayName}</dd>
        <dt>Legal name</dt>
        <dd>{t.legalName}</dd>
        <dt>Type</dt>
        <dd>{organisationTypeWord(t.organisationType)}</dd>
        <dt>NHS code</dt>
        <dd>{t.odsCode ?? 'None'}</dd>
        <dt>Country</dt>
        <dd>{COUNTRY_WORD[t.countryCode] ?? t.countryCode}</dd>
        <dt>Time zone</dt>
        <dd>{t.timeZone}</dd>
      </dl>
    </StepSection>
  );
}
