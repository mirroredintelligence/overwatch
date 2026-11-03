'use client';

import { useState, type FormEvent } from 'react';
import { TextField } from '@/components/forms/TextField';
import { Button } from '@/components/ui/Button';
import { StatusTag } from '@/components/ui/StatusTag';
import styles from '@/components/admin/admin.module.css';
import ts from '../Tenant.module.css';
import r from './Reach.module.css';
import { Said, StepSection, useWrite, type PanelProps } from './shared';

/** Step 7. The three agreements, each named by a reference. Any one can be sent alone; each is optional text. */
export function AgreementsStep(props: PanelProps) {
  const [dsa, setDsa] = useState('');
  const [dpia, setDpia] = useState('');
  const [dcb, setDcb] = useState('');
  const [problem, setProblem] = useState('');
  const write = useWrite(props.tenantId, props);
  const refs = props.detail.tenant.references;
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body: Record<string, string> = {};
    if (dsa.trim() !== '') body.dsaRef = dsa.trim();
    if (dpia.trim() !== '') body.dpiaRef = dpia.trim();
    if (dcb.trim() !== '') body.dcb0160Ref = dcb.trim();
    if (Object.keys(body).length === 0) {
      setProblem('Enter at least one reference.');
      return;
    }
    setProblem('');
    void write.run('PUT', 'references', body, () => 'Agreements saved.', () => 'The agreements could not be saved. Try again.').then((ok) => {
      if (ok) {
        setDsa('');
        setDpia('');
        setDcb('');
      }
    });
  }
  const recorded = [refs.dsa, refs.dpia, refs.dcb0160].filter((v) => v !== null).length;
  const held =(v: string | null) => v ?? 'Not recorded';
  return (
    <StepSection step={props.step} heading={props.heading}>
      <p className={ts.text}>These agreements are recommended. The organisation can go live without them, but it is better to have each in place, and the clinical safety case in particular. Record the reference of each one that is. Overwatch keeps the reference, not the document. Each can be a number, a code or a few words.</p>
      <div role="group" aria-label="Agreements, recommended, not required" className={`${r.row} ${r.rowOptional}`}>
        <p className={r.rowTitle}>
          <strong>Agreements</strong> <span className={r.rowNote}>recommended, not required</span>
        </p>
        <div className={r.rowTag}>
          <StatusTag variant={recorded === 3 ? 'done' : 'todo'}>{`${recorded} of 3 recorded`}</StatusTag>
        </div>
        <p className={r.rowDetail}>Data sharing, privacy impact, clinical safety</p>
      </div>
      {[refs.dsa, refs.dpia, refs.dcb0160].some((r) => r !== null) ? (
        <dl className={styles.facts}>
          <dt>Data sharing agreement</dt>
          <dd>{held(refs.dsa)}</dd>
          <dt>Privacy impact assessment</dt>
          <dd>{held(refs.dpia)}</dd>
          <dt>Clinical safety case</dt>
          <dd>{held(refs.dcb0160)}</dd>
        </dl>
      ) : null}
      <form className={ts.form} onSubmit={submit} noValidate aria-label="Record the agreements">
        <TextField id="ref-dsa" label="Data sharing agreement" value={dsa} onChange={(v) => { write.fresh(); setDsa(v); }} requirement="optional" />
        <TextField id="ref-dpia" label="Privacy impact assessment" value={dpia} onChange={(v) => { write.fresh(); setDpia(v); }} requirement="optional" />
        <TextField id="ref-dcb" label="Clinical safety case" value={dcb} onChange={(v) => { write.fresh(); setDcb(v); }} requirement="optional" />
        {problem !== '' ? <p className={styles.problem}>{problem}</p> : null}
        <Said say={write.say} />
        <div className={styles.actions}>
          <Button variant={props.isNext ? 'primary' : 'secondary'} type="submit" busy={write.busy}>
            Save agreements
          </Button>
        </div>
      </form>
    </StepSection>
  );
}
