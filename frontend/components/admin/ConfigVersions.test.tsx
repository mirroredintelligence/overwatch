import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { RAW_SETTINGS, VIEW_VERSIONS } from '@/test/fixtures/tenantAdmin';
import { resetAdminWrites, seenAdminWrites } from '@/test/msw/handlers/tenantAdmin';
import { SAMPLE_CSRF } from '@/test/msw/handlers/staff';
import { server } from '@/test/msw/server';
import { ConfigVersions } from './ConfigVersions';

// The settings page (TEN-076, redesign board A2): the settings in three groups beside the versions, which is in
// force, and a change drafted from it. A change is a new version; a clinical one needs two people who are not its
// author (the words say so), and the draft is made from the version the page read, so a stale one is refused by
// the back end and not overwritten here.

beforeEach(() => resetAdminWrites());

async function open() {
  const user = userEvent.setup();
  render(<ConfigVersions />);
  await screen.findByRole('list', { name: 'Configuration versions' });
  return user;
}

async function changePressure(user: ReturnType<typeof userEvent.setup>, to = '6') {
  const field = await screen.findByLabelText('Pressure watch from');
  await user.clear(field);
  await user.type(field, to);
  return field;
}

describe('the versions', () => {
  it('has one heading, Settings, and a versions panel beside the settings', async () => {
    await open();
    expect(screen.getByRole('heading', { level: 1, name: 'Settings' })).toBeInTheDocument();
    expect(screen.getByRole('complementary', { name: 'Versions' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Settings' })).toBeInTheDocument();
  });

  it('lists every version, newest first, with its state, its approvals and whether it is clinical', async () => {
    await open();
    const rows = within(screen.getByRole('list', { name: 'Configuration versions' })).getAllByRole('listitem');
    expect(rows).toHaveLength(3);
    expect(within(rows[0]!).getByRole('link', { name: 'Version 3' })).toHaveAttribute('href', '/admin/config/3');
    expect(within(rows[0]!).getByText('Waiting for approval')).toBeInTheDocument();
    expect(within(rows[0]!).getByText('0 of 2')).toBeInTheDocument();
    expect(within(rows[0]!).getByText('Clinical')).toBeInTheDocument();
    expect(within(rows[1]!).getByText('In force')).toBeInTheDocument();
    expect(within(rows[2]!).getByText('Replaced')).toBeInTheDocument();
    expect(within(rows[2]!).getByText('Operational')).toBeInTheDocument();
  });

  it('explains the rule for a clinical change before anything can be drafted', async () => {
    await open();
    expect(screen.getByText(/A change to a clinical setting is written as a draft and needs two other people\./)).toBeInTheDocument();
    expect(screen.getByText(/A change to anything else needs one\./)).toBeInTheDocument();
  });

  it('says it could not load, and offers no form, when a read fails', async () => {
    server.use(http.get('/api/bff/tenant/config/versions', () => HttpResponse.json({ code: 'exception' }, { status: 503 })));
    render(<ConfigVersions />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load the settings.');
    expect(screen.queryByRole('button', { name: 'Save draft' })).not.toBeInTheDocument();
  });

  it('says so when there are no versions yet, and drafts from version 0', async () => {
    server.use(http.get('/api/bff/tenant/config/versions', () => HttpResponse.json({ versions: [] })));
    const user = userEvent.setup();
    render(<ConfigVersions />);
    expect(await screen.findByText('No version of the settings has been made yet.')).toBeInTheDocument();
    await user.type(await screen.findByLabelText('System name'), 'Capacity A');
    await user.click(screen.getByRole('button', { name: 'Save draft' }));
    await waitFor(() => expect(seenAdminWrites).toHaveLength(1));
    expect(seenAdminWrites[0]?.body).toMatchObject({ basedOn: 0 });
  });
});

describe('drafting a change', () => {
  it('shows each setting with its words, what it is now and whether it is clinical, in three groups', async () => {
    await open();
    const clinical = await screen.findByRole('group', { name: 'Clinical settings' });
    expect(within(clinical).getByLabelText('Pressure watch from')).toHaveValue(4);
    expect(within(clinical).getByText('Now 4. Default 3. From 1 to 50.')).toBeInTheDocument();
    expect(within(clinical).getByLabelText('Twice a day second time')).toHaveValue('14:00');
    const operational = screen.getByRole('group', { name: 'Operational settings' });
    expect(within(operational).getByRole('combobox', { name: 'Alert default not updated hours' })).toHaveValue('2');
    expect(within(operational).getByRole('button', { name: 'not-updated', pressed: true })).toBeInTheDocument();
    expect(within(operational).getByRole('button', { name: 'service-closed', pressed: false })).toBeInTheDocument();
    const words = screen.getByRole('group', { name: 'The names your messages use' });
    expect(within(words).getByLabelText('System name')).toHaveValue('Capacity A');
  });

  it('shows the form without a button to open it, with Save draft off and "Nothing changed yet."', async () => {
    await open();
    expect(screen.queryByRole('button', { name: 'Draft a change' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Save draft' })).toBeDisabled();
    expect(screen.getByText('Nothing changed yet.')).toBeInTheDocument();
  });

  it('turns Save draft on and says what will happen once a setting is changed', async () => {
    const user = await open();
    await changePressure(user);
    expect(screen.getByRole('button', { name: 'Save draft' })).toBeEnabled();
    expect(screen.getByText('1 setting changed. It will be a draft until two other people approve.')).toBeInTheDocument();
  });

  it('sends only what changed, from the version in force, with the CSRF token and one idempotency key', async () => {
    const user = await open();
    await changePressure(user);
    await user.click(screen.getByRole('button', { name: 'service-closed' }));
    await user.click(screen.getByRole('button', { name: 'Save draft' }));
    await waitFor(() => expect(seenAdminWrites).toHaveLength(1));
    const [write] = seenAdminWrites;
    expect(write).toMatchObject({ method: 'POST', path: '/api/bff/tenant/config/drafts', csrf: SAMPLE_CSRF });
    expect(write?.key).toMatch(/^[\x21-\x7e]{1,200}$/);
    expect(write?.body).toEqual({ basedOn: 2, changes: { pressureWatchFrom: 6, alertDefaultKinds: ['not-updated', 'over-capacity', 'service-closed'] }, removals: [] });
  });

  it('says what happens next: the version, how many approvals, and that they are not the author’s', async () => {
    const user = await open();
    await changePressure(user);
    await user.click(screen.getByRole('button', { name: 'Save draft' }));
    const done = await screen.findByText(/Draft version 4 saved\./);
    expect(done).toHaveTextContent('Draft version 4 saved. It needs 2 approvals from people other than you.');
    expect(screen.getByRole('link', { name: 'Open version 4' })).toHaveAttribute('href', '/admin/config/4');
    // The form starts again from what is in force, so nothing is left to save twice.
    expect(screen.getByRole('button', { name: 'Save draft' })).toBeDisabled();
  });

  it('takes a setting back to its default with "Use the default", which removes the override', async () => {
    const user = await open();
    await user.click(await screen.findByRole('checkbox', { name: 'Use the default for Pressure watch from' }));
    await user.click(screen.getByRole('button', { name: 'Save draft' }));
    await waitFor(() => expect(seenAdminWrites).toHaveLength(1));
    expect(seenAdminWrites[0]?.body).toEqual({ basedOn: 2, changes: {}, removals: ['pressureWatchFrom'] });
  });

  it('refuses a number outside its bounds, in words next to the field and in the summary, and sends nothing', async () => {
    const user = await open();
    const field = await changePressure(user, '99');
    await user.click(screen.getByRole('button', { name: 'Save draft' }));
    expect(await screen.findByText('Enter a whole number from 1 to 50.', { selector: 'p' })).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('There is 1 problem');
    expect(field).toHaveAttribute('aria-invalid', 'true');
    expect(seenAdminWrites).toEqual([]);
  });

  it('refuses a time that is not HH:MM and a text that is empty', async () => {
    const user = await open();
    const time = await screen.findByLabelText('Twice a day second time');
    await user.clear(time);
    await user.type(time, '2pm');
    const name = screen.getByLabelText('System name');
    await user.clear(name);
    await user.click(screen.getByRole('button', { name: 'Save draft' }));
    expect(await screen.findByText('Enter a time as HH:MM, from 12:00 to 16:00.', { selector: 'p' })).toBeInTheDocument();
    expect(screen.getByText('Enter 1 to 60 characters.', { selector: 'p' })).toBeInTheDocument();
    expect(seenAdminWrites).toEqual([]);
  });

  it('says the settings changed while the person worked, on a 409, offers a reload, and does not overwrite', async () => {
    server.use(http.post('/api/bff/tenant/config/drafts', () => HttpResponse.json({ code: 'conflict', message: 'x' }, { status: 409 })));
    const user = await open();
    await changePressure(user);
    await user.click(screen.getByRole('button', { name: 'Save draft' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The settings changed while you were working. Reload the page and try again.');
    expect(screen.queryByText(/Draft version \d+ saved/)).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Reload the settings' }));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    expect(await screen.findByLabelText('Pressure watch from')).toHaveValue(4);
  });

  it('says the draft could not be saved, and keeps the person’s numbers, on any other failure', async () => {
    server.use(http.post('/api/bff/tenant/config/drafts', () => HttpResponse.json({ code: 'exception' }, { status: 503 })));
    const user = await open();
    const field = await changePressure(user);
    await user.click(screen.getByRole('button', { name: 'Save draft' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The draft could not be saved. Try again.');
    expect(field).toHaveValue(6);
  });

  it('uses the same idempotency key for a retry of the same submit, and a new one for the next draft', async () => {
    let fail = true;
    server.use(
      http.post('/api/bff/tenant/config/drafts', async ({ request }) => {
        seenAdminWrites.push({ method: 'POST', path: '/x', csrf: null, key: request.headers.get('idempotency-key'), body: undefined });
        if (fail) return HttpResponse.json({ code: 'exception' }, { status: 503 });
        return HttpResponse.json({ version: 4, changedKeys: [], clinicalKeys: [], approvalsRequired: 1 }, { status: 201 });
      }),
    );
    const user = await open();
    await changePressure(user);
    await user.click(screen.getByRole('button', { name: 'Save draft' }));
    await screen.findByText('The draft could not be saved. Try again.');
    fail = false;
    await user.click(screen.getByRole('button', { name: 'Save draft' }));
    await screen.findByText(/Draft version 4 saved\./);
    expect(seenAdminWrites[0]?.key).toBe(seenAdminWrites[1]?.key);
  });
});

describe('the groups', () => {
  it('shows three collapsed groups, each with its count, and opens one at a time', async () => {
    const user = await open();
    const clinical = screen.getByRole('button', { name: /Clinical settings/ });
    const operational = screen.getByRole('button', { name: /Operational settings/ });
    const words = screen.getByRole('button', { name: /The names your messages use/ });
    expect(clinical).toHaveAttribute('aria-expanded', 'false');
    expect(operational).toHaveAttribute('aria-expanded', 'false');
    expect(words).toHaveAttribute('aria-expanded', 'false');
    expect(within(clinical).getByText('2 settings')).toBeInTheDocument();
    expect(within(operational).getByText('2 settings')).toBeInTheDocument();
    expect(within(words).getByText('1 setting')).toBeInTheDocument();
    await user.click(clinical);
    expect(clinical).toHaveAttribute('aria-expanded', 'true');
    await user.click(operational);
    expect(operational).toHaveAttribute('aria-expanded', 'true');
    expect(clinical).toHaveAttribute('aria-expanded', 'false');
  });

  it('says what a change in each group needs', async () => {
    await open();
    expect(within(screen.getByRole('button', { name: /Clinical settings/ })).getByText('A change needs two approvals from other people.')).toBeInTheDocument();
    expect(within(screen.getByRole('button', { name: /Operational settings/ })).getByText('A change needs one approval.')).toBeInTheDocument();
    expect(within(screen.getByRole('button', { name: /The names your messages use/ })).getByText('Printed in texts and on screens.')).toBeInTheDocument();
  });

  it('counts what is changed on the group it is in, and says right in the form that a clinical change needs two other people', async () => {
    const user = await open();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    await changePressure(user);
    expect(within(screen.getByRole('button', { name: /Clinical settings/ })).getByText('1 changed')).toBeInTheDocument();
    const notice = screen.getByRole('status');
    expect(notice).toHaveTextContent('This changes a clinical setting.');
    expect(notice).toHaveTextContent('It needs 2 approvals from people other than you before it takes effect.');
  });

  it('marks the row that is changed, not the others', async () => {
    const user = await open();
    await changePressure(user);
    const row = screen.getByLabelText('Pressure watch from').closest('[data-changed]');
    expect(row).toHaveAttribute('data-changed', 'true');
    expect(screen.getByLabelText('Twice a day second time').closest('[data-changed]')).toHaveAttribute('data-changed', 'false');
  });

  it('does not warn about approvals for an operational change alone', async () => {
    const user = await open();
    const name = screen.getByLabelText('System name');
    await user.clear(name);
    await user.type(name, 'Capacity B');
    expect(within(screen.getByRole('button', { name: /The names your messages use/ })).getByText('1 changed')).toBeInTheDocument();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('opens the groups that match what is typed in "Find a setting", and says "n match" on the others', async () => {
    const user = await open();
    await user.type(screen.getByRole('searchbox', { name: 'Find a setting' }), 'pressure');
    const clinical = screen.getByRole('button', { name: /Clinical settings/ });
    expect(clinical).toHaveAttribute('aria-expanded', 'true');
    expect(within(clinical).getByText('1 match')).toBeInTheDocument();
    const operational = screen.getByRole('button', { name: /Operational settings/ });
    expect(operational).toHaveAttribute('aria-expanded', 'false');
    expect(within(operational).getByText('0 match')).toBeInTheDocument();
    expect(screen.getByText('1 of 5 shown')).toBeInTheDocument();
    expect(screen.queryByLabelText('System name')).not.toBeInTheDocument();
  });

  it('says "5 settings" with nothing typed, and says so when nothing matches', async () => {
    const user = await open();
    expect(screen.getByText('5 settings')).toBeInTheDocument();
    await user.type(screen.getByRole('searchbox', { name: 'Find a setting' }), 'zzzz');
    expect(await screen.findByText('No setting here matches what you typed.')).toBeInTheDocument();
    expect(screen.getByText('0 of 5 shown')).toBeInTheDocument();
  });

  it('opens the group of a setting with a problem, so the person sees what to fix', async () => {
    const user = await open();
    await changePressure(user, '99');
    await user.click(screen.getByRole('button', { name: 'Save draft' }));
    expect(await screen.findByRole('button', { name: /Clinical settings/ })).toHaveAttribute('aria-expanded', 'true');
  });
});

describe('accessibility', () => {
  it('has no axe violations with a clinical group open and a change made', async () => {
    const user = await open();
    await user.click(screen.getByRole('button', { name: /Clinical settings/ }));
    await changePressure(user);
    expect(await runAxe(document.body)).toHaveNoViolations();
  });

  it('has no axe violations as it first loads', async () => {
    await open();
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});

describe('what it does not hold', () => {
  it('shows no reference of a person', async () => {
    await open();
    expect(document.body.textContent ?? '').not.toMatch(/stf-|ops-/);
    expect(VIEW_VERSIONS.versions).toHaveLength(3);
    expect(RAW_SETTINGS.settings.length).toBeGreaterThan(0);
  });
});
