'use client';

import { useState } from 'react';
import { TextField } from '@/components/forms/TextField';
import { Button } from '@/components/ui/Button';
import { teamName } from '@/lib/operator/funnel';
import styles from '@/components/admin/admin.module.css';
import ts from '../Tenant.module.css';
import { GROUP_FAILED, Said, StepSection, isConsented, useMemberForm, useWrite, type MadeGroup, type PanelProps } from './shared';

/**
 * Step 4 (DEC-1317): once their administrator has approved, make their administrators’ team, then put the first people in
 * it. The team's name is made by the back end from the organisation's code, never typed. The administrators’ team is the
 * only route to administrator rights. Who is in a team is held in their Microsoft account, not by Overwatch.
 */
export function TeamStep(props: PanelProps) {
  const consented = isConsented(props.consent);
  const [made, setMade] = useState<MadeGroup[]>([]);
  const groups = useWrite(props.tenantId, props);
  const mapped = props.detail.roleMappings.filter((m) => m.status === 'active');
  const hasTeam = mapped.some((m) => m.role === 'tenant-admin') || made.some((g) => g.role === 'tenant-admin');
  const form = useMemberForm(props, () => 'tenant-admin', 'team');
  function makeTeam() {
    void groups.run(
      'POST',
      'entra-groups',
      { roles: [] },
      (data) => {
        setMade(data.groups ?? []);
        return 'Their administrators’ team is in place.';
      },
      GROUP_FAILED,
    );
  }
  return (
    <StepSection
      step={props.step}
      heading={props.heading}
      details={
        <>
          {made.length > 0 ? (
            <div className={styles.scroll}>
              <table className={styles.table}>
                <caption>Teams just made</caption>
                <thead>
                  <tr>
                    <th scope="col">Team</th>
                    <th scope="col">Group name</th>
                    <th scope="col">State</th>
                  </tr>
                </thead>
                <tbody>
                  {made.map((g) => (
                    <tr key={g.groupId}>
                      <td>{teamName(g.role)}</td>
                      <td>{g.name}</td>
                      <td>{g.created ? 'Made now' : 'Already there'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          <div className={styles.scroll}>
            <table className={styles.table}>
              <caption>Administrators’ team in Microsoft</caption>
              <thead>
                <tr>
                  <th scope="col">Team</th>
                  <th scope="col">Group object id</th>
                </tr>
              </thead>
              <tbody>
                {mapped.filter((m) => m.role === 'tenant-admin').length === 0 ? (
                  <tr>
                    <td colSpan={2}>Not made yet.</td>
                  </tr>
                ) : (
                  mapped
                    .filter((m) => m.role === 'tenant-admin')
                    .map((m) => (
                      <tr key={m.groupObjectId}>
                        <td>{teamName(m.role)}</td>
                        <td>{m.groupObjectId}</td>
                      </tr>
                    ))
                )}
              </tbody>
            </table>
          </div>
        </>
      }
    >
      <p className={ts.text}>The administrators’ team is the only way anyone gets administrator rights in Overwatch. They run the organisation’s own pages: who is in which team, and its settings.</p>
      {props.consent.status === 'loading' ? <p className={styles.muted}>Loading.</p> : null}
      {props.consent.status === 'ok' && !consented ? <p className={ts.text}>You can create their administrators’ team once their administrator has approved Overwatch.</p> : null}
      {consented && !hasTeam ? (
        <>
          <Said say={groups.say} />
          <div className={styles.actions}>
            <Button variant={props.isNext ? 'primary' : 'secondary'} busy={groups.busy} onClick={makeTeam}>
              Create their administrators’ team
            </Button>
          </div>
        </>
      ) : null}
      {consented && hasTeam ? (
        <>
          <p className={styles.ok}>Their administrators’ team is added to Overwatch.</p>
          <Said say={groups.say} />
          <h4 className={ts.subTitle}>Add an administrator</h4>
          <form className={ts.form} onSubmit={form.submit} noValidate aria-label="Add the first administrator by email">
            <TextField id="first-admin-email" label="Administrator’s work email" value={form.email} onChange={(v) => { form.member.fresh(); form.setEmail(v); }} requirement="none" inputMode="email" autoComplete="off" error={form.error} />
            <Said say={form.member.say} />
            <div className={styles.actions}>
              <Button variant="secondary" type="submit" busy={form.member.busy}>
                Add the first administrator by email
              </Button>
            </div>
          </form>
        </>
      ) : null}
    </StepSection>
  );
}
