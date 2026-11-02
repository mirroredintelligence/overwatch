import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetAdminWrites, seenAdminWrites } from '@/test/msw/handlers/tenantAdmin';
import { SAMPLE_CSRF } from '@/test/msw/handlers/staff';
import { server } from '@/test/msw/server';
import { ContactsForm } from './ContactsForm';

// The organisation's contacts (TEN-076): one of each kind. The organisation's own business lines and
// addresses, never a person's.

beforeEach(() => resetAdminWrites());

async function open() {
  const user = userEvent.setup();
  render(<ContactsForm />);
  await screen.findByRole('heading', { level: 1, name: 'Contacts' });
  await screen.findByDisplayValue('01632 960001');
  return user;
}

describe('ContactsForm', () => {
  it('has one section for each of the four kinds, filled with what is held', async () => {
    await open();
    for (const name of ['Coordination phone', 'Support email', 'Shift lead escalation', 'Clinical safety officer']) {
      expect(screen.getByRole('group', { name })).toBeInTheDocument();
    }
    const phone = screen.getByRole('group', { name: 'Coordination phone' });
    expect(within(phone).getByLabelText('Label')).toHaveValue('Access team A');
    expect(within(phone).getByLabelText('Number or address')).toHaveValue('01632 960001');
    expect(within(screen.getByRole('group', { name: 'Support email' })).getByLabelText('Label')).toHaveValue('');
  });

  it('saves one kind at a time, with the CSRF token and a key', async () => {
    const user = await open();
    const group = screen.getByRole('group', { name: 'Support email' });
    await user.type(within(group).getByLabelText('Label'), 'Support desk');
    await user.type(within(group).getByLabelText('Number or address'), 'support@a.example.test');
    await user.click(within(group).getByRole('button', { name: 'Save support email' }));
    await waitFor(() => expect(seenAdminWrites).toHaveLength(1));
    expect(seenAdminWrites[0]).toMatchObject({
      method: 'PUT',
      path: '/api/bff/tenant/contacts',
      csrf: SAMPLE_CSRF,
      body: { kind: 'support-email', label: 'Support desk', value: 'support@a.example.test' },
    });
    expect(seenAdminWrites[0]?.key).toBeTruthy();
    expect(await within(group).findByRole('status')).toHaveTextContent('Saved.');
  });

  it('asks for both the label and the number or address, and sends nothing without them', async () => {
    const user = await open();
    const group = screen.getByRole('group', { name: 'Shift lead escalation' });
    await user.click(within(group).getByRole('button', { name: 'Save shift lead escalation' }));
    expect(await within(group).findByText('Enter a label.', { selector: 'p' })).toBeInTheDocument();
    expect(within(group).getByText('Enter a phone number.', { selector: 'p' })).toBeInTheDocument();
    expect(seenAdminWrites).toEqual([]);
  });

  it('says an email address does not work for the shift lead line, and sends nothing', async () => {
    const user = await open();
    const group = screen.getByRole('group', { name: 'Shift lead escalation' });
    await user.type(within(group).getByLabelText('Label'), 'Shift lead desk');
    await user.type(within(group).getByLabelText('Number or address'), 'lead@a.example.test');
    await user.click(within(group).getByRole('button', { name: 'Save shift lead escalation' }));
    expect(await within(group).findByText(/An email address does not work here/, { selector: 'p' })).toBeInTheDocument();
    expect(seenAdminWrites).toEqual([]);
  });

  it('says that one kind could not be saved without losing the others', async () => {
    server.use(http.put('/api/bff/tenant/contacts', () => HttpResponse.json({}, { status: 503 })));
    const user = await open();
    const group = screen.getByRole('group', { name: 'Coordination phone' });
    await user.type(within(group).getByLabelText('Label'), ' 2');
    await user.click(within(group).getByRole('button', { name: 'Save coordination phone' }));
    expect(await within(group).findByRole('alert')).toHaveTextContent('This contact could not be saved. Try again.');
    expect(within(group).getByLabelText('Label')).toHaveValue('Access team A 2');
  });

  it('says in each closed row what is held, or that nothing is set, with its form behind the row', async () => {
    await open();
    const phone = screen.getByRole('button', { name: /Coordination phone/ });
    expect(phone).toHaveAttribute('aria-expanded', 'false');
    expect(within(phone).getByText('Access team A · 01632 960001')).toBeInTheDocument();
    expect(within(phone).getByText('Set')).toBeInTheDocument();
    const email = screen.getByRole('button', { name: /Support email/ });
    expect(within(email).getByText('Nothing is set yet.')).toBeInTheDocument();
    expect(within(email).getByText('Not set')).toBeInTheDocument();
  });

  it('opens one kind at a time', async () => {
    const user = await open();
    const phone = screen.getByRole('button', { name: /Coordination phone/ });
    const email = screen.getByRole('button', { name: /Support email/ });
    await user.click(phone);
    expect(phone).toHaveAttribute('aria-expanded', 'true');
    await user.click(email);
    expect(email).toHaveAttribute('aria-expanded', 'true');
    expect(phone).toHaveAttribute('aria-expanded', 'false');
  });

  it('shows what was saved in the row straight away, without a reload', async () => {
    const user = await open();
    await user.click(screen.getByRole('button', { name: /Support email/ }));
    const group = screen.getByRole('group', { name: 'Support email' });
    await user.type(within(group).getByLabelText('Label'), 'Support desk');
    await user.type(within(group).getByLabelText('Number or address'), 'support@a.example.test');
    await user.click(within(group).getByRole('button', { name: 'Save support email' }));
    const row = screen.getByRole('button', { name: /Support email/ });
    expect(await within(row).findByText('Support desk · support@a.example.test')).toBeInTheDocument();
    expect(within(row).getByText('Set')).toBeInTheDocument();
  });

  it('says it could not load when the read fails', async () => {
    server.use(http.get('/api/bff/tenant/overview', () => HttpResponse.json({}, { status: 503 })));
    render(<ContactsForm />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load the contacts.');
  });

  it('has no axe violations', async () => {
    await open();
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});
