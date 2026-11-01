import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { GROUP_ADMIN, GROUP_LEAD, MEMBER_SAM, RAW_GROUPS } from '@/test/fixtures/tenantAdmin';
import { resetAdminWrites, seenAdminWrites } from '@/test/msw/handlers/tenantAdmin';
import { SAMPLE_CSRF } from '@/test/msw/handlers/staff';
import { server } from '@/test/msw/server';
import { GroupMembers } from './GroupMembers';

// Groups and members (DEC-1317): the groups Overwatch made in the organisation's directory and who is in each.
// The page adds and removes people through its own BFF routes; which groups may be changed is the back end's
// decision, so the page never sends a group name, only the id the list gave.

beforeEach(() => resetAdminWrites());

async function open() {
  const user = userEvent.setup();
  render(<GroupMembers />);
  await screen.findByRole('region', { name: 'Administrators group' });
  return user;
}

const lead = () => screen.getByRole('region', { name: 'Shift lead group' });
const admins = () => screen.getByRole('region', { name: 'Administrators group' });

describe('what is shown', () => {
  it('lists each group Overwatch made with its directory name and who is in it', async () => {
    await open();
    expect(within(admins()).getByText('RXX01_overwatch_tenant-admin')).toBeInTheDocument();
    const table = within(lead()).getByRole('table', { name: 'Members of the shift lead group' });
    expect(within(table).getByRole('row', { name: /Jane Sample jane\.sample@example\.test/ })).toBeInTheDocument();
    expect(within(table).getByRole('row', { name: /Sam Second —/ })).toBeInTheDocument();
  });

  it('says so when nobody is in a group', async () => {
    server.use(http.get('/api/bff/tenant/groups', () => HttpResponse.json({ setUp: true, groups: [{ ...RAW_GROUPS.groups[1]!, members: [] }] })));
    render(<GroupMembers />);
    expect(await screen.findByText('No one is in this group.')).toBeInTheDocument();
  });

  it('says the groups are not set up yet, with no forms, before the operator has made them', async () => {
    server.use(http.get('/api/bff/tenant/groups', () => HttpResponse.json({ setUp: false, groups: [] })));
    render(<GroupMembers />);
    expect(await screen.findByText(/have not been set up yet/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Add person/ })).not.toBeInTheDocument();
  });

  it('says it could not load, with no forms, when the read fails', async () => {
    server.use(http.get('/api/bff/tenant/groups', () => HttpResponse.json({}, { status: 503 })));
    render(<GroupMembers />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load the groups.');
    expect(screen.queryByRole('button', { name: /Add person/ })).not.toBeInTheDocument();
  });

  it('shows a group deleted in the directory as missing, with the one next step and no way to change it', async () => {
    server.use(http.get('/api/bff/tenant/groups', () => HttpResponse.json({ setUp: true, groups: [{ groupId: GROUP_LEAD, name: null, role: 'lead', missing: true, members: [] }] })));
    render(<GroupMembers />);
    expect(await screen.findByRole('alert')).toHaveTextContent('This group is no longer in your directory. Ask the platform operator to set the groups up again.');
    expect(screen.queryByRole('button', { name: /Add person/ })).not.toBeInTheDocument();
  });
});

describe('adding a person', () => {
  it('sends the address to the group id the list gave, with the CSRF token and a key, and says it was added', async () => {
    const user = await open();
    await user.type(within(lead()).getByLabelText('Work email of the person to add to the shift lead group'), 'new.person@example.test');
    await user.click(within(lead()).getByRole('button', { name: 'Add person to the shift lead group' }));
    await waitFor(() => expect(seenAdminWrites).toHaveLength(1));
    expect(seenAdminWrites[0]).toMatchObject({ method: 'POST', path: `/api/bff/tenant/groups/${GROUP_LEAD}/members`, csrf: SAMPLE_CSRF, body: { email: 'new.person@example.test' } });
    expect(seenAdminWrites[0]?.key).toBeTruthy();
    expect(await within(lead()).findByRole('status')).toHaveTextContent('Added to the group.');
  });

  it('never sends a group name: only the address, and only the id in the path', async () => {
    const user = await open();
    await user.type(within(admins()).getByLabelText(/Work email of the person to add/), 'a.b@example.test');
    await user.click(within(admins()).getByRole('button', { name: /Add person/ }));
    await waitFor(() => expect(seenAdminWrites).toHaveLength(1));
    expect(Object.keys(seenAdminWrites[0]!.body as object)).toEqual(['email']);
    expect(seenAdminWrites[0]?.path).toBe(`/api/bff/tenant/groups/${GROUP_ADMIN}/members`);
  });

  it('refuses something that is not an address, in words, and sends nothing', async () => {
    const user = await open();
    await user.type(within(lead()).getByLabelText(/Work email of the person to add/), 'not an address');
    await user.click(within(lead()).getByRole('button', { name: /Add person/ }));
    expect(await within(lead()).findByText('Enter the person’s work email address, for example name@organisation.nhs.uk.', { selector: 'p' })).toBeInTheDocument();
    expect(seenAdminWrites).toEqual([]);
  });

  it('says no one has that address when the directory does not know it', async () => {
    server.use(http.post('/api/bff/tenant/groups/:group/members', () => HttpResponse.json({ code: 'invalid' }, { status: 400 })));
    const user = await open();
    await user.type(within(lead()).getByLabelText(/Work email of the person to add/), 'ghost@example.test');
    await user.click(within(lead()).getByRole('button', { name: /Add person/ }));
    expect(await within(lead()).findByRole('alert')).toHaveTextContent('No one in your directory has that address.');
  });

  it('says the group cannot be changed here when the back end refuses it as not one it manages', async () => {
    server.use(http.post('/api/bff/tenant/groups/:group/members', () => HttpResponse.json({ code: 'not-found' }, { status: 404 })));
    const user = await open();
    await user.type(within(lead()).getByLabelText(/Work email of the person to add/), 'a.b@example.test');
    await user.click(within(lead()).getByRole('button', { name: /Add person/ }));
    expect(await within(lead()).findByRole('alert')).toHaveTextContent('That group cannot be changed here.');
  });

  it('says to try again when the directory could not be reached', async () => {
    server.use(http.post('/api/bff/tenant/groups/:group/members', () => HttpResponse.json({ code: 'transient' }, { status: 503 })));
    const user = await open();
    await user.type(within(lead()).getByLabelText(/Work email of the person to add/), 'a.b@example.test');
    await user.click(within(lead()).getByRole('button', { name: /Add person/ }));
    expect(await within(lead()).findByRole('alert')).toHaveTextContent('The directory could not be reached. Try again in a minute.');
  });

  it('says a person who was already in is already in, not that they were added', async () => {
    server.use(http.post('/api/bff/tenant/groups/:group/members', () => HttpResponse.json({ groupId: GROUP_LEAD, changed: false })));
    const user = await open();
    await user.type(within(lead()).getByLabelText(/Work email of the person to add/), 'jane.sample@example.test');
    await user.click(within(lead()).getByRole('button', { name: /Add person/ }));
    expect(await within(lead()).findByRole('status')).toHaveTextContent('That person is already in the group.');
  });
});

describe('removing a person', () => {
  it('asks to confirm, then sends the delete for that group and that person only', async () => {
    const user = await open();
    await user.click(within(lead()).getByRole('button', { name: 'Remove Sam Second from the shift lead group' }));
    expect(seenAdminWrites).toEqual([]); // one click is not enough
    await user.click(within(lead()).getByRole('button', { name: 'Yes, remove Sam Second from the shift lead group' }));
    await waitFor(() => expect(seenAdminWrites).toHaveLength(1));
    expect(seenAdminWrites[0]).toMatchObject({ method: 'DELETE', path: `/api/bff/tenant/groups/${GROUP_LEAD}/members/${MEMBER_SAM}`, csrf: SAMPLE_CSRF });
    expect(seenAdminWrites[0]?.key).toBeTruthy();
    expect(await within(lead()).findByRole('status')).toHaveTextContent('Removed from the group.');
  });

  it('can be cancelled without sending anything', async () => {
    const user = await open();
    await user.click(within(lead()).getByRole('button', { name: 'Remove Jane Sample from the shift lead group' }));
    await user.click(within(lead()).getByRole('button', { name: 'Cancel removing Jane Sample' }));
    expect(seenAdminWrites).toEqual([]);
    expect(within(lead()).getByRole('button', { name: 'Remove Jane Sample from the shift lead group' })).toBeInTheDocument();
  });

  it('says why when the last administrator cannot be removed', async () => {
    server.use(http.delete('/api/bff/tenant/groups/:group/members/:user', () => HttpResponse.json({ code: 'conflict' }, { status: 409 })));
    const user = await open();
    await user.click(within(admins()).getByRole('button', { name: 'Remove Jane Sample from the administrators group' }));
    await user.click(within(admins()).getByRole('button', { name: /Yes, remove/ }));
    expect(await within(admins()).findByRole('alert')).toHaveTextContent('this is the last administrator, who cannot be removed');
  });
});

describe('the page', () => {
  it('has no axe violations', async () => {
    await open();
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});
