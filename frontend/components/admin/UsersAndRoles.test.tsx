import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { DIRECTORY, GROUP, VIEW_OVERVIEW } from '@/test/fixtures/tenantAdmin';
import { resetAdminWrites, seenAdminWrites } from '@/test/msw/handlers/tenantAdmin';
import { SAMPLE_CSRF } from '@/test/msw/handlers/staff';
import { server } from '@/test/msw/server';
import { UsersAndRoles } from './UsersAndRoles';

// Users and roles (TEN-076): the directory the organisation signs in with and which of its groups gets which
// role. A directory is bound as pending and stays so until the platform operator verifies it; a group is never
// mapped to the administrator role (the first administrator is invited by the platform operator).

beforeEach(() => resetAdminWrites());
const GUID = '22222222-2222-4222-8222-222222222222';

async function open() {
  const user = userEvent.setup();
  render(<UsersAndRoles />);
  await screen.findByRole('table', { name: 'Directories' });
  return user;
}

describe('what is bound now', () => {
  it('lists the directory with its state in words and when it was verified', async () => {
    await open();
    const row = within(screen.getByRole('table', { name: 'Directories' })).getByRole('row', { name: new RegExp(DIRECTORY) });
    expect(within(row).getByText('Verified')).toBeInTheDocument();
    expect(within(row).getByText('19 Oct 2026, 11:00')).toBeInTheDocument();
  });

  it('lists the role mappings with their role and state', async () => {
    await open();
    const row = within(screen.getByRole('table', { name: 'Role mappings' })).getByRole('row', { name: new RegExp(GROUP) });
    expect(within(row).getByText('Shift lead')).toBeInTheDocument();
    expect(within(row).getByText('In use')).toBeInTheDocument();
  });

  it('says the first administrator is invited by the platform operator, and that a group cannot be mapped to it', async () => {
    await open();
    expect(screen.getByText(/The first administrator is invited by the platform operator/)).toBeInTheDocument();
    const select = screen.getByRole('combobox', { name: 'Role' });
    expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual(['Advisor', 'Clinical lead', 'Shift lead', 'Criteria owner', 'Planning', 'Audit']);
  });

  it('says it could not load, with no forms, when the read fails', async () => {
    server.use(http.get('/api/bff/tenant/overview', () => HttpResponse.json({}, { status: 503 })));
    render(<UsersAndRoles />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load the directory and roles.');
    expect(screen.queryByRole('button', { name: 'Bind directory' })).not.toBeInTheDocument();
  });
});

describe('binding a directory', () => {
  it('sends the directory id with the CSRF token and a key, and says it stays pending until verified', async () => {
    const user = await open();
    await user.type(screen.getByLabelText('Directory id'), GUID);
    await user.click(screen.getByRole('button', { name: 'Bind directory' }));
    await waitFor(() => expect(seenAdminWrites).toHaveLength(1));
    expect(seenAdminWrites[0]).toMatchObject({ method: 'PUT', path: '/api/bff/tenant/directory', csrf: SAMPLE_CSRF, body: { directoryId: GUID } });
    expect(seenAdminWrites[0]?.key).toBeTruthy();
    expect(await screen.findByRole('status')).toHaveTextContent('Directory saved. It stays pending until the platform operator verifies it.');
  });

  it('refuses an id that is not a directory id, in words, and sends nothing', async () => {
    const user = await open();
    await user.type(screen.getByLabelText('Directory id'), 'not-an-id');
    await user.click(screen.getByRole('button', { name: 'Bind directory' }));
    expect(await screen.findByText('Enter the directory id as it is shown in your directory, for example 00000000-0000-0000-0000-000000000000.', { selector: 'p' })).toBeInTheDocument();
    expect(seenAdminWrites).toEqual([]);
  });

  it('says it could not be saved on a failure', async () => {
    server.use(http.put('/api/bff/tenant/directory', () => HttpResponse.json({}, { status: 503 })));
    const user = await open();
    await user.type(screen.getByLabelText('Directory id'), GUID);
    await user.click(screen.getByRole('button', { name: 'Bind directory' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The directory could not be saved. Try again.');
  });
});

describe('mapping a group to a role', () => {
  it('sends the group and the role as active', async () => {
    const user = await open();
    await user.type(screen.getByLabelText('Group id'), GUID);
    await user.selectOptions(screen.getByRole('combobox', { name: 'Role' }), 'clinical');
    await user.click(screen.getByRole('button', { name: 'Map group' }));
    await waitFor(() => expect(seenAdminWrites).toHaveLength(1));
    expect(seenAdminWrites[0]).toMatchObject({ method: 'PUT', path: '/api/bff/tenant/role-mappings', body: { groupObjectId: GUID, role: 'clinical', status: 'active' } });
    expect(await screen.findByRole('status')).toHaveTextContent('Group mapped.');
  });

  it('retires a mapping that is in use, with the same group and role', async () => {
    const user = await open();
    await user.click(screen.getByRole('button', { name: `Stop using the mapping for group ${GROUP}` }));
    await waitFor(() => expect(seenAdminWrites).toHaveLength(1));
    expect(seenAdminWrites[0]?.body).toEqual({ groupObjectId: GROUP, role: 'lead', status: 'retired' });
  });

  it('offers no stop on a mapping already retired', async () => {
    server.use(http.get('/api/bff/tenant/overview', () => HttpResponse.json({ ...VIEW_OVERVIEW, mappings: [{ groupObjectId: GROUP, role: 'lead', status: 'retired' }] })));
    await open();
    expect(screen.queryByRole('button', { name: /Stop using the mapping/ })).not.toBeInTheDocument();
    expect(screen.getByText('Stopped')).toBeInTheDocument();
  });

  it('refuses an empty group id', async () => {
    const user = await open();
    await user.click(screen.getByRole('button', { name: 'Map group' }));
    expect(await screen.findByText('Enter the group id.', { selector: 'p' })).toBeInTheDocument();
    expect(seenAdminWrites).toEqual([]);
  });

  it('has no axe violations', async () => {
    await open();
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});
