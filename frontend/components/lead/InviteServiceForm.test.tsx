import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { resetLeadPosts, seenLeadPosts } from '@/test/msw/handlers/lead';
import { server } from '@/test/msw/server';
import { InviteServiceForm } from './InviteServiceForm';

// Invite a service (DEC-1341): the service goes on the scope list, then its lead is invited, in one press.

let scopePosts: unknown[] = [];

beforeEach(() => {
  resetLeadPosts();
  scopePosts = [];
  document.cookie = 'overwatch_csrf=csrf-for-invite; path=/';
  server.use(
    http.post('/api/bff/scope', async ({ request }) => {
      scopePosts.push(await request.json());
      return HttpResponse.json({ serviceId: 's-new-1' }, { status: 201 });
    }),
  );
});

async function fill(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText('Service name'), 'UCR South');
  await user.click(screen.getAllByRole('radio')[0]);
  await user.type(screen.getByLabelText(/Service lead.s name/), 'Dee Lead');
  await user.type(screen.getByLabelText(/Service lead.s mobile number/), '07700 900444');
}

describe('InviteServiceForm', () => {
  it('asks for every field and sends nothing until they are right', async () => {
    const user = userEvent.setup();
    render(<InviteServiceForm />);

    await user.click(byEl('LEAD-INVITE-SERVICE-BTN'));

    expect(screen.getByText('Enter the service name')).toBeInTheDocument();
    expect(screen.getByText('Choose a category')).toBeInTheDocument();
    expect(screen.getByText('Enter the name of the service lead')).toBeInTheDocument();
    expect(screen.getByText(/Enter a UK mobile number/)).toBeInTheDocument();
    expect(scopePosts).toHaveLength(0);
    expect(seenLeadPosts).toHaveLength(0);
  });

  it('adds the service to the scope list as in the pilot, then invites its lead by text, and says so', async () => {
    const user = userEvent.setup();
    render(<InviteServiceForm />);
    await fill(user);

    await user.click(byEl('LEAD-INVITE-SERVICE-BTN'));

    expect(await screen.findByText('Invitation sent')).toBeInTheDocument();
    expect(scopePosts).toEqual([expect.objectContaining({ name: 'UCR South', flag: 'in-pilot' })]);
    expect(seenLeadPosts.at(-1)).toMatchObject({
      path: '/api/bff/lead/invitations',
      body: { serviceId: 's-new-1', role: 'Service lead', phone: '07700 900444', channel: 'text' },
    });
    expect(screen.getByText(/UCR South is on the scope list/)).toBeInTheDocument();
  });

  it('says the service was added but not invited when the invitation fails, and links to invite it without a second entry', async () => {
    const user = userEvent.setup();
    server.use(http.post('/api/bff/lead/invitations', () => HttpResponse.json({ code: 'x' }, { status: 500 })));
    render(<InviteServiceForm />);
    await fill(user);

    await user.click(byEl('LEAD-INVITE-SERVICE-BTN'));

    expect(await screen.findByText('UCR South was added, but not invited')).toBeInTheDocument();
    expect(byEl('LEAD-INVITE-SERVICE-RETRY-LINK')).toHaveAttribute('href', '/lead/reporters/invite?service=s-new-1');
    expect(scopePosts).toHaveLength(1);
  });

  it('invites nobody when the service could not be added', async () => {
    const user = userEvent.setup();
    server.use(http.post('/api/bff/scope', () => HttpResponse.json({ code: 'x' }, { status: 500 })));
    render(<InviteServiceForm />);
    await fill(user);

    await user.click(byEl('LEAD-INVITE-SERVICE-BTN'));

    expect(await screen.findByRole('alert')).toHaveTextContent('The service could not be added');
    expect(seenLeadPosts).toHaveLength(0);
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<InviteServiceForm />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
