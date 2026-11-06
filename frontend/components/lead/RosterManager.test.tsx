import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { resetLeadPosts, seenLeadPosts } from '@/test/msw/handlers/lead';
import { server } from '@/test/msw/server';
import { RosterManager } from './RosterManager';

// The duty roster of a service (DEC-1341): who is on it, who is on shift, and adding and removing a person.

beforeEach(() => {
  resetLeadPosts();
  document.cookie = 'overwatch_csrf=csrf-for-the-roster; path=/';
});

async function loaded() {
  const view = render(<RosterManager serviceId="s-virtual-ward" />);
  await screen.findByText('Ana Duty');
  return view;
}

describe('RosterManager', () => {
  it('lists each person with the last four digits and whether they are on shift', async () => {
    await loaded();
    const list = byEl('LEAD-ROSTER');
    expect(within(list).getByText(/Number ending 0111 · On shift until/)).toBeInTheDocument();
    expect(within(list).getByText('Number ending 0222 · Off shift')).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/07700/);
  });

  it('says how a duty manager checks in, in words', async () => {
    await loaded();
    expect(screen.getByText(/texts ON when they start, or ON 8 for eight hours, and OFF when they finish/)).toBeInTheDocument();
  });

  it('adds a person, says so beside the button, clears the form and reads the roster again', async () => {
    const user = userEvent.setup();
    await loaded();

    await user.type(screen.getByLabelText('Name'), 'Cara Duty');
    await user.type(screen.getByLabelText('Mobile number'), '07700 900333');
    await user.click(byEl('LEAD-ROSTER-ADD-BTN'));

    expect(await screen.findByText('Added Cara Duty. They are off shift until they text ON.')).toBeInTheDocument();
    expect(seenLeadPosts.at(-1)).toMatchObject({
      path: '/api/bff/lead/services/s-virtual-ward/roster',
      body: { name: 'Cara Duty', mobile: '07700 900333' },
    });
    expect(seenLeadPosts.at(-1)?.csrf).toBe('csrf-for-the-roster');
    expect(seenLeadPosts.at(-1)?.idempotencyKey).toBeTruthy();
    expect(screen.getByLabelText('Name')).toHaveValue('');
    expect(screen.getByLabelText('Mobile number')).toHaveValue('');
  });

  it('asks for a name and a UK mobile number, and sends nothing until both are right', async () => {
    const user = userEvent.setup();
    await loaded();

    await user.type(screen.getByLabelText('Name'), 'A');
    await user.type(screen.getByLabelText('Mobile number'), '12345');
    await user.click(byEl('LEAD-ROSTER-ADD-BTN'));

    expect(screen.getByText('Enter a name, 2 to 60 characters.')).toBeInTheDocument();
    expect(screen.getByText('Enter a UK mobile number, for example 07700 900123.')).toBeInTheDocument();
    expect(screen.getByLabelText('Name')).toHaveAttribute('aria-invalid', 'true');
    expect(seenLeadPosts).toHaveLength(0);
  });

  it('says that the person is already on the roster when the back end answers 409', async () => {
    server.use(http.post('/api/bff/lead/services/:id/roster', () => HttpResponse.json({ code: 'conflict' }, { status: 409 })));
    const user = userEvent.setup();
    await loaded();

    await user.type(screen.getByLabelText('Name'), 'Ana Duty');
    await user.type(screen.getByLabelText('Mobile number'), '07700 900111');
    await user.click(byEl('LEAD-ROSTER-ADD-BTN'));

    expect(await screen.findByText('That person is already on this roster.')).toBeInTheDocument();
  });

  it('asks before removing, and removes only when confirmed', async () => {
    const user = userEvent.setup();
    await loaded();

    await user.click(screen.getByRole('button', { name: 'Remove Ben Duty from the roster' }));
    expect(seenLeadPosts).toHaveLength(0);
    await user.click(screen.getByRole('button', { name: 'Remove Ben Duty now' }));

    expect(await screen.findByText('Removed Ben Duty from the roster.')).toBeInTheDocument();
    expect(seenLeadPosts.at(-1)?.path).toBe('/api/bff/lead/roster/role-ben/remove');
  });

  it('keeps the person when the lead chooses Keep', async () => {
    const user = userEvent.setup();
    await loaded();

    await user.click(screen.getByRole('button', { name: 'Remove Ben Duty from the roster' }));
    await user.click(screen.getByRole('button', { name: 'Keep' }));

    expect(seenLeadPosts).toHaveLength(0);
    expect(screen.getByRole('button', { name: 'Remove Ben Duty from the roster' })).toBeInTheDocument();
  });

  it('says when the roster is empty', async () => {
    server.use(http.get('/api/bff/lead/services/:id/roster', () => HttpResponse.json({ managers: [] })));
    render(<RosterManager serviceId="s-virtual-ward" />);
    expect(await screen.findByText(/No one is on the roster yet/)).toBeInTheDocument();
  });

  it('says so, and shows no roster, when it cannot be read', async () => {
    server.use(http.get('/api/bff/lead/services/:id/roster', () => HttpResponse.json({}, { status: 503 })));
    render(<RosterManager serviceId="s-virtual-ward" />);
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('The roster could not be read. Try again.'));
    expect(screen.queryByText('On the roster')).toBeNull();
  });

  it('has no axe violations', async () => {
    const { container } = await loaded();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
