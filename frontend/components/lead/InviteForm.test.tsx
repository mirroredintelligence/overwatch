import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { SERVICE_UCR_EAST } from '@/test/fixtures/lead';
import { resetLeadPosts, seenLeadPosts } from '@/test/msw/handlers/lead';
import { server } from '@/test/msw/server';
import { InviteForm } from './InviteForm';

// Invite a reporter (W43). Only a service in the pilot can be invited: the back end says so with a 409.

beforeEach(() => {
  resetLeadPosts();
  document.cookie = 'diucs_csrf=test-csrf-token';
});

describe('InviteForm', () => {
  it('prefills the service from the link, and previews the text it will send', async () => {
    render(<InviteForm serviceId={SERVICE_UCR_EAST} />);
    expect(await screen.findByLabelText('Service')).toHaveValue(SERVICE_UCR_EAST);
    expect(screen.getByText(/You are invited to report capacity for UCR East\./)).toBeInTheDocument();
    expect(screen.getByText(/Valid for 48 hrs\./)).toBeInTheDocument();
  });

  it('refuses a mobile that is not a UK mobile, with the example for this form', async () => {
    const user = userEvent.setup();
    render(<InviteForm serviceId={SERVICE_UCR_EAST} />);
    await user.type(await screen.findByLabelText('Role'), 'Duty manager');
    await user.type(screen.getByLabelText('Mobile number'), '0123');
    await user.click(screen.getByRole('button', { name: 'Send invitation' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Enter a UK mobile number, like 07700 900123');
    expect(seenLeadPosts).toHaveLength(0);
  });

  it('posts the invitation with the chosen channel, and says it was sent', async () => {
    const user = userEvent.setup();
    render(<InviteForm serviceId={SERVICE_UCR_EAST} />);
    await user.type(await screen.findByLabelText('Role'), 'Duty manager');
    await user.type(screen.getByLabelText('Mobile number'), '07700 900123');
    await user.click(screen.getByRole('radio', { name: 'Text' }));
    await user.click(screen.getByRole('button', { name: 'Send invitation' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Invitation sent.');
    expect(seenLeadPosts[0]).toMatchObject({
      path: '/api/bff/lead/invitations',
      csrf: 'test-csrf-token',
      body: { serviceId: SERVICE_UCR_EAST, role: 'Duty manager', phone: '07700 900123', channel: 'text' },
    });
    expect(seenLeadPosts[0].idempotencyKey).toBeTruthy();
  });

  it('says the service is not in the pilot when the back end refuses it with a 409', async () => {
    server.use(http.post('/api/bff/lead/invitations', () => HttpResponse.json({ code: 'not-in-pilot' }, { status: 409 })));
    const user = userEvent.setup();
    render(<InviteForm serviceId={SERVICE_UCR_EAST} />);
    await user.type(await screen.findByLabelText('Role'), 'Duty manager');
    await user.type(screen.getByLabelText('Mobile number'), '07700 900123');
    await user.click(screen.getByRole('button', { name: 'Send invitation' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('This service is not in the pilot scope list.');
  });

  it('has no axe violations', async () => {
    const { container } = render(<InviteForm serviceId={SERVICE_UCR_EAST} />);
    await screen.findByLabelText('Service');
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
