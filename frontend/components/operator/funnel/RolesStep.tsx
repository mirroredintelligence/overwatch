'use client';

import { useState, type FormEvent } from 'react';
import { TextField } from '@/components/forms/TextField';
import { Button } from '@/components/ui/Button';
import { TEAM_WORDS, teamName } from '@/lib/operator/funnel';
import styles from '@/components/admin/admin.module.css';
import ts from '../Tenant.module.css';
import { GROUP_FAILED, Said, StepSection, isConsented, useMemberForm, useWrite, type MadeGroup, type PanelProps } from './shared';

/** Step 5. The other teams and what each can do. A team is added to Overwatch once, by ticking it here. */
export function RolesStep(props: PanelProps) {
  const consented = isConsented(props.consent);
  const [ticked, setTicked] = useState<string[]>([]);
  const [made, setMade] = useState<MadeGroup[]>([]);
  const groups = useWrite(props.tenantId, props);
  const mapped = props.detail.roleMappings.filter((m) => m.status === 'active');
  const has = (code: string) => mapped.some((m) => m.role === code) || made.some((g) => g.role === code);
  const memberChoices = TEAM_WORDS.filter(([code]) => has(code));
  const [memberRole, setMemberRole] = useState('');
  const chosenRole = memberChoices.some(([code]) => code === memberRole) ? memberRole : (memberChoices[0]?.[0] ?? '');
  const form = useMemberForm(props, () => chosenRole, 'team');
  function toggle(code: string, on: boolean) {
    groups.fresh();
    setTicked((held) => (on ? [...held, code] : held.filter((c) => c !== code)));
  }
  function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void groups
      .run(
        'POST',
        'entra-groups',
        { roles: ticked },
        (data) => {
          setMade(data.groups ?? []);
          return 'The teams are added to Overwatch.';
        },
        GROUP_FAILED,
      )
      .then((ok) => {
        if (ok) setTicked([]);
      });
  }
  const rest = mapped.filter((m) => m.role !== 'tenant-admin');
  return (
    <StepSection
      step={props.step}
      heading={props.heading}
      details={
        <div className={styles.scroll}>
          <table className={`${styles.table} ${styles.stackTable}`}>
            <caption>Teams in Microsoft</caption>
            <thead>
              <tr>
                <th scope="col">Team</th>
                <th scope="col">Group object id</th>
                <th scope="col">State</th>
              </tr>
            </thead>
            <tbody>
              {rest.length === 0 ? (
                <tr>
                  <td colSpan={3}>No team is added yet.</td>
                </tr>
              ) : (
                rest.map((m) => (
                  <tr key={`${m.groupObjectId}-${m.role}`}>
                    <td data-label="Team">{teamName(m.role)}</td>
                    <td data-label="Group object id">{m.groupObjectId}</td>
                    <td data-label="State">{m.status === 'active' ? 'In use' : 'Stopped'}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      }
    >
      <p className={ts.text}>Everyone else works in one of these teams. Being in a team is what lets a person do its work in Overwatch. The administrators’ team above is the only route to administrator rights: none of these teams gives them.</p>
      {props.consent.status === 'ok' && !consented ? <p className={ts.text}>Teams can be added once their administrator has approved Overwatch.</p> : null}
      <form className={ts.form} onSubmit={add} noValidate aria-label="Add teams to Overwatch">
        <ul className={ts.teamList}>
          {TEAM_WORDS.map(([code, word, can]) => (
            <li key={code}>
              {has(code) ? (
                <strong>{word}</strong>
              ) : consented ? (
                <label>
                  <input type="checkbox" checked={ticked.includes(code)} onChange={(event) => toggle(code, event.target.checked)} /> <strong>{word}</strong>
                </label>
              ) : (
                <strong>{word}</strong>
              )}{' '}
              <span className={has(code) ? styles.tag : `${styles.tag} ${styles.tagDashed}`}>{has(code) ? 'Added to Overwatch' : 'Not added yet'}</span>
              <span className={styles.muted}>{can}</span>
            </li>
          ))}
        </ul>
        <Said say={groups.say} />
        {consented ? (
          <div className={styles.actions}>
            <Button variant={props.isNext ? 'primary' : 'secondary'} type="submit" busy={groups.busy} disabled={ticked.length === 0}>
              Add the ticked teams
            </Button>
          </div>
        ) : null}
      </form>
      {consented && memberChoices.length > 0 ? (
        <>
        <h4 className={ts.subTitle}>Add people to a team</h4>
        <form className={ts.form} onSubmit={form.submit} noValidate aria-label="Add a person to a team">
          <div className={styles.selectLabel}>
            <label htmlFor="team-member-team">Team</label>
            <select id="team-member-team" className={styles.select} value={chosenRole} onChange={(event) => { form.member.fresh(); setMemberRole(event.target.value); }}>
              {memberChoices.map(([code, word]) => (
                <option key={code} value={code}>
                  {word}
                </option>
              ))}
            </select>
          </div>
          <TextField id="team-member-email" label="Person’s work email" value={form.email} onChange={(v) => { form.member.fresh(); form.setEmail(v); }} requirement="none" inputMode="email" autoComplete="off" error={form.error} />
          <Said say={form.member.say} />
          <div className={styles.actions}>
            <Button variant="secondary" type="submit" busy={form.member.busy}>
              Add to team
            </Button>
          </div>
        </form>
        </>
      ) : null}
    </StepSection>
  );
}
