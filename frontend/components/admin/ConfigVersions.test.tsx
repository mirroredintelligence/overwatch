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

// The settings page (TEN-076): the versions, which is in force, and a change drafted from it. A change is a
// new version; a clinical one needs two people who are not its author (the words say so), and the draft is
// made from the version the page read, so a stale one is refused by the back end and not overwritten here.

beforeEach(() => resetAdminWrites());

async function open() {
  const user = userEvent.setup();
  render(<ConfigVersions />);
  await screen.findByRole('list', { name: 'Configuration versions' });
  return user;
}

describe('the versions', () => {
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
    expect(screen.getByText(/A change to a clinical setting needs two people to approve it/)).toBeInTheDocument();
    expect(screen.getByText(/The person who wrote it cannot be one of them\./)).toBeInTheDocument();
  });

  it('says it could not load, and offers no draft, when a read fails', async () => {
    server.use(http.get('/api/bff/tenant/config/versions', () => HttpResponse.json({ code: 'exception' }, { status: 503 })));
    render(<ConfigVersions />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load the settings.');
    expect(screen.queryByRole('button', { name: 'Draft a change' })).not.toBeInTheDocument();
  });

  it('says so when there are no versions yet, and drafts from version 0', async () => {
    server.use(http.get('/api/bff/tenant/config/versions', () => HttpResponse.json({ versions: [] })));
    const user = userEvent.setup();
    render(<ConfigVersions />);
    expect(await screen.findByText('No version of the settings has been made yet.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Draft a change' }));
    await user.type(await screen.findByLabelText('System name'), 'Capacity A');
    await user.click(screen.getByRole('button', { name: 'Save draft' }));
    await waitFor(() => expect(seenAdminWrites).toHaveLength(1));
    expect(seenAdminWrites[0]?.body).toMatchObject({ basedOn: 0 });
  });
});

describe('drafting a change', () => {
  it('shows each setting with its words, what it is now and whether it is clinical, grouped by class', async () => {
    const user = await open();
    await user.click(screen.getByRole('button', { name: 'Draft a change' }));
    const clinical = await screen.findByRole('group', { name: 'Clinical settings' });
    expect(within(clinical).getByLabelText('Pressure watch from')).toHaveValue(4);
    expect(within(clinical).getByText('Now 4. Default 3. From 1 to 50.')).toBeInTheDocument();
    expect(within(clinical).getByLabelText('Twice a day second time')).toHaveValue('14:00');
    const operational = screen.getByRole('group', { name: 'Operational settings' });
    expect(within(operational).getByLabelText('System name')).toHaveValue('Capacity A');
    expect(within(operational).getByRole('combobox', { name: 'Alert default not updated hours' })).toHaveValue('2');
    expect(within(operational).getByRole('checkbox', { name: 'not-updated' })).toBeChecked();
    expect(within(operational).getByRole('checkbox', { name: 'service-closed' })).not.toBeChecked();
  });

  it('says there is nothing to save when nothing changed, and sends nothing', async () => {
    const user = await open();
    await user.click(screen.getByRole('button', { name: 'Draft a change' }));
    await user.click(await screen.findByRole('button', { name: 'Save draft' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('You have not changed anything.');
    expect(seenAdminWrites).toEqual([]);
  });

  it('sends only what changed, from the version in force, with the CSRF token and one idempotency key', async () => {
    const user = await open();
    await user.click(screen.getByRole('button', { name: 'Draft a change' }));
    const field = await screen.findByLabelText('Pressure watch from');
    await user.clear(field);
    await user.type(field, '6');
    await user.click(screen.getByRole('checkbox', { name: 'service-closed' }));
    await user.click(screen.getByRole('button', { name: 'Save draft' }));
    await waitFor(() => expect(seenAdminWrites).toHaveLength(1));
    const [write] = seenAdminWrites;
    expect(write).toMatchObject({ method: 'POST', path: '/api/bff/tenant/config/drafts', csrf: SAMPLE_CSRF });
    expect(write?.key).toMatch(/^[\x21-\x7e]{1,200}$/);
    expect(write?.body).toEqual({ basedOn: 2, changes: { pressureWatchFrom: 6, alertDefaultKinds: ['not-updated', 'over-capacity', 'service-closed'] }, removals: [] });
  });

  it('says what happens next: the version, how many approvals, and that they are not the author’s', async () => {
    const user = await open();
    await user.click(screen.getByRole('button', { name: 'Draft a change' }));
    const field = await screen.findByLabelText('Pressure watch from');
    await user.clear(field);
    await user.type(field, '6');
    await user.click(screen.getByRole('button', { name: 'Save draft' }));
    const done = await screen.findByRole('status');
    expect(done).toHaveTextContent('Draft version 4 saved. It needs 2 approvals from people other than you.');
    expect(within(done).getByRole('link', { name: 'Open version 4' })).toHaveAttribute('href', '/admin/config/4');
  });

  it('takes a setting back to its default with "Use the default", which removes the override', async () => {
    const user = await open();
    await user.click(screen.getByRole('button', { name: 'Draft a change' }));
    await user.click(await screen.findByRole('checkbox', { name: 'Use the default for Pressure watch from' }));
    await user.click(screen.getByRole('button', { name: 'Save draft' }));
    await waitFor(() => expect(seenAdminWrites).toHaveLength(1));
    expect(seenAdminWrites[0]?.body).toEqual({ basedOn: 2, changes: {}, removals: ['pressureWatchFrom'] });
  });

  it('refuses a number outside its bounds, in words next to the field and in the summary, and sends nothing', async () => {
    const user = await open();
    await user.click(screen.getByRole('button', { name: 'Draft a change' }));
    const field = await screen.findByLabelText('Pressure watch from');
    await user.clear(field);
    await user.type(field, '99');
    await user.click(screen.getByRole('button', { name: 'Save draft' }));
    expect(await screen.findByText('Enter a whole number from 1 to 50.', { selector: 'p' })).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('There is 1 problem');
    expect(field).toHaveAttribute('aria-invalid', 'true');
    expect(seenAdminWrites).toEqual([]);
  });

  it('refuses a time that is not HH:MM and a text that is empty', async () => {
    const user = await open();
    await user.click(screen.getByRole('button', { name: 'Draft a change' }));
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

  it('says the settings changed while the person worked, on a 409, and does not overwrite', async () => {
    server.use(http.post('/api/bff/tenant/config/drafts', () => HttpResponse.json({ code: 'conflict', message: 'x' }, { status: 409 })));
    const user = await open();
    await user.click(screen.getByRole('button', { name: 'Draft a change' }));
    const field = await screen.findByLabelText('Pressure watch from');
    await user.clear(field);
    await user.type(field, '6');
    await user.click(screen.getByRole('button', { name: 'Save draft' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The settings changed while you were working. Reload the page and try again.');
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('says the draft could not be saved, and keeps the person’s numbers, on any other failure', async () => {
    server.use(http.post('/api/bff/tenant/config/drafts', () => HttpResponse.json({ code: 'exception' }, { status: 503 })));
    const user = await open();
    await user.click(screen.getByRole('button', { name: 'Draft a change' }));
    const field = await screen.findByLabelText('Pressure watch from');
    await user.clear(field);
    await user.type(field, '6');
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
    await user.click(screen.getByRole('button', { name: 'Draft a change' }));
    const field = await screen.findByLabelText('Pressure watch from');
    await user.clear(field);
    await user.type(field, '6');
    await user.click(screen.getByRole('button', { name: 'Save draft' }));
    await screen.findByText('The draft could not be saved. Try again.');
    fail = false;
    await user.click(screen.getByRole('button', { name: 'Save draft' }));
    await screen.findByRole('status');
    expect(seenAdminWrites[0]?.key).toBe(seenAdminWrites[1]?.key);
  });
});

describe('a draft that does not fill the screen', () => {
  async function draft() {
    const user = await open();
    await user.click(screen.getByRole('button', { name: 'Draft a change' }));
    await screen.findByRole('group', { name: 'Clinical settings' });
    return user;
  }

  it('shows the settings as two collapsed groups with a count, and opens one at a time', async () => {
    const user = await draft();
    const clinical = screen.getByRole('button', { name: /Clinical settings/ });
    const operational = screen.getByRole('button', { name: /Operational settings/ });
    expect(clinical).toHaveAttribute('aria-expanded', 'false');
    expect(operational).toHaveAttribute('aria-expanded', 'false');
    await user.click(clinical);
    expect(clinical).toHaveAttribute('aria-expanded', 'true');
    await user.click(operational);
    expect(operational).toHaveAttribute('aria-expanded', 'true');
    expect(clinical).toHaveAttribute('aria-expanded', 'false');
  });

  it('counts what is changed on the group it is in, and says right in the form that a clinical change needs two other people', async () => {
    const user = await draft();
    expect(screen.queryByText(/so it needs two approvals from people other than you/)).not.toBeInTheDocument();
    const field = screen.getByLabelText('Pressure watch from');
    await user.clear(field);
    await user.type(field, '6');
    expect(within(screen.getByRole('button', { name: /Clinical settings/ })).getByText('1 changed')).toBeInTheDocument();
    expect(screen.getByText(/This changes a clinical setting \(Pressure watch from\), so it needs two approvals from people other than you\./)).toBeInTheDocument();
  });

  it('does not warn about approvals for an operational change alone', async () => {
    const user = await draft();
    const name = screen.getByLabelText('System name');
    await user.clear(name);
    await user.type(name, 'Capacity B');
    expect(within(screen.getByRole('button', { name: /Operational settings/ })).getByText('1 changed')).toBeInTheDocument();
    expect(screen.queryByText(/so it needs two approvals from people other than you/)).not.toBeInTheDocument();
  });

  it('narrows the settings as you type in "Find a setting", opening the groups that match', async () => {
    const user = await draft();
    await user.type(screen.getByLabelText('Find a setting'), 'pressure');
    expect(screen.getByLabelText('Pressure watch from')).toBeInTheDocument();
    expect(screen.queryByLabelText('System name')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Clinical settings/ })).toHaveAttribute('aria-expanded', 'true');
    expect(screen.queryByRole('button', { name: /Operational settings/ })).not.toBeInTheDocument();
  });

  it('says so when nothing matches the filter', async () => {
    const user = await draft();
    await user.type(screen.getByLabelText('Find a setting'), 'zzzz');
    expect(await screen.findByText('No setting matches that. Try fewer letters.')).toBeInTheDocument();
  });

  it('opens the group of a setting with a problem, so the person sees what to fix', async () => {
    const user = await draft();
    const field = screen.getByLabelText('Pressure watch from');
    await user.clear(field);
    await user.type(field, '99');
    await user.click(screen.getByRole('button', { name: 'Save draft' }));
    expect(await screen.findByRole('button', { name: /Clinical settings/ })).toHaveAttribute('aria-expanded', 'true');
  });
});

describe('accessibility', () => {
  it('has no axe violations with the form open', async () => {
    const user = await open();
    await user.click(screen.getByRole('button', { name: 'Draft a change' }));
    await screen.findByRole('group', { name: 'Clinical settings' });
    const { container } = { container: document.body };
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('has no axe violations as a list', async () => {
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
