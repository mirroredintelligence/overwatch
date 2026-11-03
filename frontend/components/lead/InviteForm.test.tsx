import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { SERVICE_UCR_EAST } from '@/test/fixtures/lead';
import { resetLeadPosts, seenLeadPosts } from '@/test/msw/handlers/lead';
import { server } from '@/test/msw/server';
import { InviteForm } from './InviteForm';

// Invite a reporter (W43; INV-02). The compose panel: the form, and the text they get beside it. Only a
// service in the pilot can be invited: the back end says so with a 409.

beforeEach(() => {
  resetLeadPosts();
  document.cookie = 'overwatch_csrf=test-csrf-token';
});

describe('InviteForm', () => {
  it('is the compose panel: a heading, the promise of three minutes, and the form beside the text preview', async () => {
    render(<InviteForm serviceId={SERVICE_UCR_EAST} />);
    const panel = screen.getByRole('region', { name: 'Invite a reporter' });
    expect(within(panel).getByRole('heading', { level: 2, name: 'Invite a reporter' })).toBeInTheDocument();
    expect(within(panel).getByText('They set up in about 3 minutes, on their own phone.')).toBeInTheDocument();
    expect(within(panel).getByRole('complementary', { name: 'The text we send' })).toBeInTheDocument();
    await screen.findByLabelText('Service');
  });

  it('prefills the service from the link, and previews the text it will send', async () => {
    render(<InviteForm serviceId={SERVICE_UCR_EAST} />);
    expect(await screen.findByLabelText('Service')).toHaveValue(SERVICE_UCR_EAST);
    expect(screen.getByText(/you are invited to report capacity for UCR East\./)).toBeInTheDocument();
    expect(screen.getByText(/The link works for 48 hours\./)).toBeInTheDocument();
  });

  it('updates the preview when the service field is left, not as the choice is made', async () => {
    const user = userEvent.setup();
    render(<InviteForm serviceId={SERVICE_UCR_EAST} />);
    const select = await screen.findByLabelText('Service');
    const live = within(screen.getByRole('complementary', { name: 'The text we send' })).getByRole('status');
    await user.selectOptions(select, 'Reablement');
    expect(live).toHaveTextContent('UCR East');
    expect(live).not.toHaveTextContent('Reablement');
    await user.tab();
    expect(live).toHaveTextContent('report capacity for Reablement.');
  });

  it('asks for their role, and describes the phone as one that stays with the post', async () => {
    render(<InviteForm serviceId={SERVICE_UCR_EAST} />);
    expect(await screen.findByLabelText('Their role')).toBeInTheDocument();
    expect(screen.getByText(/It stays with the post, not the person\./)).toBeInTheDocument();
  });

  it('offers the three ways to report as a group, with Text chosen to begin with', async () => {
    render(<InviteForm serviceId={SERVICE_UCR_EAST} />);
    const group = await screen.findByRole('group', { name: 'Suggest how they report' });
    expect(within(group).getAllByRole('radio').map((radio) => radio.getAttribute('value'))).toEqual(['push', 'text', 'email']);
    expect(within(group).getByRole('radio', { name: 'Text' })).toBeChecked();
    expect(within(group).getByText('They can change this while setting up.')).toBeInTheDocument();
  });

  it('says only pilot services can be invited, and points to the scope list', async () => {
    render(<InviteForm serviceId={SERVICE_UCR_EAST} />);
    expect(screen.getByText('Only services in the pilot')).toBeInTheDocument();
    expect(screen.getByText(/Add one on the scope list first\./)).toBeInTheDocument();
    await screen.findByLabelText('Service');
  });

  it('offers Cancel, which goes back to the reporters page and posts nothing (ShiftLeadInvite)', async () => {
    render(<InviteForm serviceId={SERVICE_UCR_EAST} />);
    expect(await screen.findByRole('link', { name: 'Cancel' })).toHaveAttribute('href', '/lead/reporters');
    expect(seenLeadPosts).toHaveLength(0);
  });

  it('refuses a mobile that is not a UK mobile, with the example for this form', async () => {
    const user = userEvent.setup();
    render(<InviteForm serviceId={SERVICE_UCR_EAST} />);
    await user.type(await screen.findByLabelText('Their role'), 'Duty manager');
    await user.type(screen.getByLabelText('Mobile number'), '0123');
    await user.click(screen.getByRole('button', { name: 'Send invitation' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Enter a UK mobile number, like 07700 900123');
    expect(seenLeadPosts).toHaveLength(0);
  });

  it('posts the invitation with the chosen channel, and says it was sent', async () => {
    const user = userEvent.setup();
    render(<InviteForm serviceId={SERVICE_UCR_EAST} />);
    await user.type(await screen.findByLabelText('Their role'), 'Duty manager');
    await user.type(screen.getByLabelText('Mobile number'), '07700 900123');
    await user.click(screen.getByRole('radio', { name: 'Text' }));
    await user.click(screen.getByRole('button', { name: 'Send invitation' }));
    expect(await screen.findByText(/^Invitation sent\./)).toBeInTheDocument();
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
    await user.type(await screen.findByLabelText('Their role'), 'Duty manager');
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
