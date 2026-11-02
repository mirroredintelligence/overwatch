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

// People and roles (DEC-1317): one row per role Overwatch made in the organisation's directory, saying who has it,
// opening one at a time to show the people and a search to add someone. The page adds and removes people through
// its own BFF routes; which groups may be changed is the back end's decision, so the page never sends a group
// name, only the id the list gave, and only the address the directory search returned.

beforeEach(() => resetAdminWrites());

async function open() {
  const user = userEvent.setup();
  render(<GroupMembers />);
  await screen.findByRole('region', { name: 'Administrators group' });
  return user;
}

const lead = () => screen.getByRole('region', { name: 'Shift lead group' });
const admins = () => screen.getByRole('region', { name: 'Administrators group' });

async function openLead(user: ReturnType<typeof userEvent.setup>) {
  await user.click(within(lead()).getByRole('button', { name: /Shift lead/ }));
  return lead();
}

async function search(user: ReturnType<typeof userEvent.setup>, group: HTMLElement, words: string) {
  // The search opens from the Add button, and only then.
  if (!within(group).queryByRole('combobox')) await user.click(within(group).getByRole('button', { name: /^Add someone/ }));
  const box = within(group).getByRole('combobox', { name: 'Search your directory' });
  await user.type(box, words);
  return box;
}

describe('what is shown', () => {
  it('says in each row who has the role, without opening it', async () => {
    await open();
    expect(within(admins()).getAllByText('Jane Sample').length).toBeGreaterThan(0);
    expect(within(lead()).getByText('Jane Sample and Sam Second')).toBeInTheDocument();
    expect(within(lead()).getByText('2 people')).toBeInTheDocument();
    expect(within(admins()).getByText('1 person')).toBeInTheDocument();
  });

  it('opens one role at a time and says which is open', async () => {
    const user = await open();
    const leadButton = within(lead()).getByRole('button', { name: /Shift lead/ });
    const adminButton = within(admins()).getByRole('button', { name: /Administrators/ });
    expect(leadButton).toHaveAttribute('aria-expanded', 'false');
    await user.click(leadButton);
    expect(leadButton).toHaveAttribute('aria-expanded', 'true');
    await user.click(adminButton);
    expect(adminButton).toHaveAttribute('aria-expanded', 'true');
    expect(leadButton).toHaveAttribute('aria-expanded', 'false');
  });

  it('lists the directory name and the people of an open role', async () => {
    const user = await open();
    await openLead(user);
    expect(within(lead()).getByText('RXX01_overwatch_lead')).toBeInTheDocument();
    const list = within(lead()).getByRole('list', { name: 'Members of the shift lead group' });
    expect(within(list).getByText('jane.sample@example.test')).toBeInTheDocument();
    expect(within(list).getByText('Sam Second')).toBeInTheDocument();
  });

  it('says so when nobody is in a group', async () => {
    server.use(http.get('/api/bff/tenant/groups', () => HttpResponse.json({ setUp: true, groups: [{ ...RAW_GROUPS.groups[1]!, members: [] }] })));
    const user = userEvent.setup();
    render(<GroupMembers />);
    expect(await screen.findByText('Open to add the first person.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Shift lead/ }));
    expect(screen.getByText('No one is in this group.')).toBeInTheDocument();
  });

  it('says the groups are not set up yet, with no rows, before the operator has made them', async () => {
    server.use(http.get('/api/bff/tenant/groups', () => HttpResponse.json({ setUp: false, groups: [] })));
    render(<GroupMembers />);
    expect(await screen.findByText(/have not been set up yet/)).toBeInTheDocument();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  });

  it('says it could not load, with no rows, when the read fails', async () => {
    server.use(http.get('/api/bff/tenant/groups', () => HttpResponse.json({}, { status: 503 })));
    render(<GroupMembers />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load the groups.');
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  });

  it('shows a group deleted in the directory as missing, with the one next step and no way to change it', async () => {
    server.use(http.get('/api/bff/tenant/groups', () => HttpResponse.json({ setUp: true, groups: [{ groupId: GROUP_LEAD, name: null, role: 'lead', missing: true, members: [] }] })));
    render(<GroupMembers />);
    expect(await screen.findByRole('alert')).toHaveTextContent('This group is no longer in your directory. Ask the platform operator to set the groups up again.');
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  });
});

describe('finding and adding a person', () => {
  it('shows no search until Add is chosen, and takes it away again on Close search', async () => {
    const user = await open();
    const group = await openLead(user);
    expect(within(group).queryByRole('combobox')).not.toBeInTheDocument();
    await user.click(within(group).getByRole('button', { name: 'Add someone to the shift lead group' }));
    expect(within(group).getByRole('combobox', { name: 'Search your directory' })).toBeInTheDocument();
    await user.click(within(group).getByRole('button', { name: 'Close search to the shift lead group' }));
    expect(within(group).queryByRole('combobox')).not.toBeInTheDocument();
  });

  it('keeps the directory name of the group behind Details until it is asked for', async () => {
    const user = await open();
    const group = await openLead(user);
    const details = within(group).getByText('Details').closest('details')!;
    expect(details).not.toHaveAttribute('open');
    await user.click(within(group).getByText('Details'));
    expect(details).toHaveAttribute('open');
    expect(within(details).getByText('RXX01_overwatch_lead')).toBeVisible();
  });

  it('searches the directory as you type and lists who matches, saying who is already in the role', async () => {
    const user = await open();
    const group = await openLead(user);
    await search(user, group, 'ja');
    const list = await within(group).findByRole('listbox', { name: 'Search your directory' });
    const options = await within(list).findAllByRole('option');
    expect(options.map((o) => o.textContent)).toEqual([
      expect.stringContaining('Jane Sample'),
      expect.stringContaining('Jasmine Newcomer'),
    ]);
    expect(within(options[0]!).getByText('Already in this role')).toBeInTheDocument();
    expect(options[0]).toHaveAttribute('aria-disabled', 'true');
    expect(options[1]).toHaveAttribute('aria-disabled', 'false');
  });

  it('asks for two letters before it searches, and says when no one matches', async () => {
    const user = await open();
    const group = await openLead(user);
    const box = await search(user, group, 'j');
    expect(within(group).getByRole('listbox', { hidden: true })).not.toBeVisible();
    await user.clear(box);
    await user.type(box, 'zz');
    expect(await within(group).findByText(/No one in your directory matches that/)).toBeInTheDocument();
  });

  it('adds the person chosen, by the address the directory gave, to the group id the list gave', async () => {
    const user = await open();
    const group = await openLead(user);
    await search(user, group, 'jas');
    await user.click(await within(group).findByRole('option', { name: /Jasmine Newcomer/ }));
    await waitFor(() => expect(seenAdminWrites).toHaveLength(1));
    expect(seenAdminWrites[0]).toMatchObject({ method: 'POST', path: `/api/bff/tenant/groups/${GROUP_LEAD}/members`, csrf: SAMPLE_CSRF, body: { email: 'jasmine.newcomer@example.test' } });
    expect(Object.keys(seenAdminWrites[0]!.body as object)).toEqual(['email']);
    expect(seenAdminWrites[0]?.key).toBeTruthy();
    expect(await within(group).findByText('Added to the group.')).toBeInTheDocument();
  });

  it('shows the person added at once, even while the directory still lists the old people', async () => {
    // The mock answers the groups read with the same people every time, as the directory does just after a change.
    const user = await open();
    const group = await openLead(user);
    await search(user, group, 'jas');
    await user.click(await within(group).findByRole('option', { name: /Jasmine Newcomer/ }));
    const list = await within(group).findByRole('list', { name: 'Members of the shift lead group' });
    expect(await within(list).findByText('Jasmine Newcomer')).toBeInTheDocument();
    expect(within(group).getByText('3 people')).toBeInTheDocument();
  });

  it('works from the keyboard: arrow to a person, Enter to add', async () => {
    const user = await open();
    const group = await openLead(user);
    const box = await search(user, group, 'jas');
    await within(group).findByRole('option', { name: /Jasmine Newcomer/ });
    await user.keyboard('{ArrowDown}');
    expect(box).toHaveAttribute('aria-activedescendant');
    await user.keyboard('{Enter}');
    await waitFor(() => expect(seenAdminWrites).toHaveLength(1));
    expect(seenAdminWrites[0]?.path).toBe(`/api/bff/tenant/groups/${GROUP_LEAD}/members`);
  });

  it('does not add a person already in the role, or one with no address to add them by', async () => {
    const user = await open();
    const group = await openLead(user);
    await search(user, group, 'sa');
    await user.click(await within(group).findByRole('option', { name: /Sam Second/ }));
    await user.clear(within(group).getByRole('combobox'));
    await search(user, group, 'jane');
    await user.click(await within(group).findByRole('option', { name: /Jane Sample/ }));
    expect(seenAdminWrites).toEqual([]);
  });

  it('says the directory could not be searched when the search fails', async () => {
    server.use(http.get('/api/bff/tenant/people', () => HttpResponse.json({}, { status: 503 })));
    const user = await open();
    const group = await openLead(user);
    await search(user, group, 'ja');
    expect(await within(group).findByText('The directory could not be searched. Try again in a minute.')).toBeInTheDocument();
  });

  it('says no one has that address when the directory refuses the add as unknown', async () => {
    server.use(http.post('/api/bff/tenant/groups/:group/members', () => HttpResponse.json({ code: 'invalid' }, { status: 400 })));
    const user = await open();
    const group = await openLead(user);
    await search(user, group, 'jas');
    await user.click(await within(group).findByRole('option', { name: /Jasmine Newcomer/ }));
    expect(await within(group).findByRole('alert')).toHaveTextContent('No one in your directory has that address.');
  });

  it('says the group cannot be changed here when the back end refuses it as not one it manages', async () => {
    server.use(http.post('/api/bff/tenant/groups/:group/members', () => HttpResponse.json({ code: 'not-found' }, { status: 404 })));
    const user = await open();
    const group = await openLead(user);
    await search(user, group, 'jas');
    await user.click(await within(group).findByRole('option', { name: /Jasmine Newcomer/ }));
    expect(await within(group).findByRole('alert')).toHaveTextContent('That group cannot be changed here.');
  });

  it('says to try again when the directory could not be reached', async () => {
    server.use(http.post('/api/bff/tenant/groups/:group/members', () => HttpResponse.json({ code: 'transient' }, { status: 503 })));
    const user = await open();
    const group = await openLead(user);
    await search(user, group, 'jas');
    await user.click(await within(group).findByRole('option', { name: /Jasmine Newcomer/ }));
    expect(await within(group).findByRole('alert')).toHaveTextContent('The directory could not be reached. Try again in a minute.');
  });
});

describe('removing a person', () => {
  it('asks to confirm, then sends the delete for that group and that person only', async () => {
    const user = await open();
    const group = await openLead(user);
    await user.click(within(group).getByRole('button', { name: 'Remove Sam Second from the shift lead group' }));
    expect(seenAdminWrites).toEqual([]); // one click is not enough
    await user.click(within(group).getByRole('button', { name: 'Yes, remove Sam Second from the shift lead group' }));
    await waitFor(() => expect(seenAdminWrites).toHaveLength(1));
    expect(seenAdminWrites[0]).toMatchObject({ method: 'DELETE', path: `/api/bff/tenant/groups/${GROUP_LEAD}/members/${MEMBER_SAM}`, csrf: SAMPLE_CSRF });
    expect(seenAdminWrites[0]?.key).toBeTruthy();
    expect(await within(group).findByText('Removed from the group.')).toBeInTheDocument();
  });

  it('takes the person out of the list at once, even while the directory still lists them', async () => {
    const user = await open();
    const group = await openLead(user);
    await user.click(within(group).getByRole('button', { name: 'Remove Sam Second from the shift lead group' }));
    await user.click(within(group).getByRole('button', { name: /Yes, remove Sam Second/ }));
    await waitFor(() => expect(within(group).getByText('1 person')).toBeInTheDocument());
    const list = within(group).getByRole('list', { name: 'Members of the shift lead group' });
    expect(within(list).queryByText('Sam Second')).not.toBeInTheDocument();
  });

  it('can be cancelled without sending anything', async () => {
    const user = await open();
    const group = await openLead(user);
    await user.click(within(group).getByRole('button', { name: 'Remove Jane Sample from the shift lead group' }));
    await user.click(within(group).getByRole('button', { name: 'Cancel removing Jane Sample' }));
    expect(seenAdminWrites).toEqual([]);
    expect(within(group).getByRole('button', { name: 'Remove Jane Sample from the shift lead group' })).toBeInTheDocument();
  });

  it('says why when the last administrator cannot be removed', async () => {
    server.use(http.delete('/api/bff/tenant/groups/:group/members/:user', () => HttpResponse.json({ code: 'conflict' }, { status: 409 })));
    const user = await open();
    await user.click(within(admins()).getByRole('button', { name: /Administrators/ }));
    await user.click(within(admins()).getByRole('button', { name: 'Remove Jane Sample from the administrators group' }));
    await user.click(within(admins()).getByRole('button', { name: /Yes, remove/ }));
    expect(await within(admins()).findByRole('alert')).toHaveTextContent('this is the last administrator, who cannot be removed');
    expect(GROUP_ADMIN).toBeTruthy();
  });
});

describe('the page', () => {
  it('has no axe violations, closed or with a role open', async () => {
    const user = await open();
    expect(await runAxe(document.body)).toHaveNoViolations();
    await openLead(user);
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});
