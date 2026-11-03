'use client';

import { StatusTag } from '@/components/ui/StatusTag';
import { organisationTypeWord, TENANT_STATUS_WORD } from '@/lib/operator/words';
import { whenText } from '@/lib/tenantAdmin/words';
import styles from '@/components/admin/admin.module.css';
import ts from '../Tenant.module.css';
import parts from './Parts.module.css';
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
      <div className={parts.row} data-state="done">
        <span className={parts.mark} aria-hidden="true">
          ●
        </span>
        <div className={parts.rowBody}>
          <b className={parts.rowTitle}>NHS record checked</b>
          <span className={parts.rowSub}>{`${t.displayName} · ${t.odsCode ?? 'No NHS code'} · ${TENANT_STATUS_WORD[t.status] ?? t.status}`}</span>
          <dl className={parts.facts}>
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
        </div>
        <StatusTag variant="done">Done</StatusTag>
      </div>
    </StepSection>
  );
}
