import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { VIEW_OVERVIEW } from '@/test/fixtures/tenantAdmin';
import { resetAdminWrites, seenAdminWrites } from '@/test/msw/handlers/tenantAdmin';
import { SAMPLE_CSRF } from '@/test/msw/handlers/staff';
import { server } from '@/test/msw/server';
import { EmailSender } from './EmailSender';

// The email channel (TEN-076, DEC-1007 item 3): the organisation manages its own email sender. The TEXT
// channel is the platform operator's and the screen says so; it shows no field for it. The reference of a
// channel's secret is never shown or typed here: only whether the channel has sign-in details. Board A6 (left
// half): two cards, the text card read only, and the email card with a choice between the organisation's own
// address and not set up.

const NO_EMAIL = { ...VIEW_OVERVIEW, channels: VIEW_OVERVIEW.channels.filter((c) => c.kind === 'sms') };

beforeEach(() => resetAdminWrites());

async function open() {
  const user = userEvent.setup();
  render(<EmailSender />);
  await screen.findByRole('heading', { level: 1, name: 'Email sender' });
  await waitFor(() => expect(screen.getByLabelText('Sender name')).toHaveValue('Sample A team'));
  return user;
}

async function openNotSetUp() {
  server.use(http.get('/api/bff/tenant/overview', () => HttpResponse.json(NO_EMAIL)));
  const user = userEvent.setup();
  render(<EmailSender />);
  await screen.findByRole('heading', { level: 1, name: 'Email sender' });
  await screen.findByRole('radio', { name: 'Use your own address' });
  return user;
}

describe('the page', () => {
  it('has a senders section with the heading and the two cards', async () => {
    await open();
    const senders = screen.getByRole('region', { name: 'Senders' });
    expect(within(senders).getByRole('heading', { level: 2, name: 'Who messages come from' })).toBeInTheDocument();
    expect(within(senders).getByRole('region', { name: 'Text messages' })).toBeInTheDocument();
    expect(within(senders).getByRole('region', { name: 'Email' })).toBeInTheDocument();
  });
});

describe('the text channel', () => {
  it('says texts go out from the shared line, and shows it read only', async () => {
    await open();
    const text = screen.getByRole('region', { name: 'Text messages' });
    expect(within(text).getByText('Using the shared line')).toBeInTheDocument();
    expect(
      within(text).getByText(
        "Texts go out from Overwatch's shared line until your organisation has its own number. People cannot reply by text yet. To change this, ask the platform team.",
      ),
    ).toBeInTheDocument();
    expect(within(text).queryByRole('textbox')).not.toBeInTheDocument();
    expect(within(text).queryByRole('button')).not.toBeInTheDocument();
  });
});

describe('the email channel', () => {
  it('shows In use, whether it has sign-in details, and never the details', async () => {
    await open();
    const email = screen.getByRole('region', { name: 'Email' });
    expect(within(email).getByText('In use')).toBeInTheDocument();
    expect(within(email).getByText('Sign-in details: not set')).toBeInTheDocument();
    expect(document.body.textContent ?? '').not.toMatch(/tenants\/|secretRef/);
  });

  it('shows the sender details in the fields of the own address', async () => {
    await open();
    expect(screen.getByRole('radio', { name: 'Use your own address' })).toBeChecked();
    expect(screen.getByLabelText('Sender name')).toHaveValue('Sample A team');
    expect(screen.getByLabelText('From address')).toHaveValue('noreply@a.example.test');
    expect(screen.getByLabelText('From display name')).toHaveValue('Sample A');
  });

  it('shows Stopped for a sender that has been stopped', async () => {
    server.use(
      http.get('/api/bff/tenant/overview', () =>
        HttpResponse.json({ ...VIEW_OVERVIEW, channels: VIEW_OVERVIEW.channels.map((c) => (c.kind === 'email' ? { ...c, status: 'retired' } : c)) }),
      ),
    );
    render(<EmailSender />);
    await screen.findByRole('heading', { level: 1, name: 'Email sender' });
    const email = await screen.findByRole('region', { name: 'Email' });
    expect(within(email).getByText('Stopped')).toBeInTheDocument();
    expect(within(email).queryByText('In use')).not.toBeInTheDocument();
  });

  it('shows Not set up, with the own address not chosen and no fields, when there is no email sender', async () => {
    await openNotSetUp();
    const email = screen.getByRole('region', { name: 'Email' });
    expect(within(email).getByText('Not set up')).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Use your own address' })).not.toBeChecked();
    expect(screen.queryByLabelText('Sender name')).not.toBeInTheDocument();
  });

  it('shows the fields when the own address is chosen', async () => {
    const user = await openNotSetUp();
    await user.click(screen.getByRole('radio', { name: 'Use your own address' }));
    expect(screen.getByLabelText('Sender name')).toBeInTheDocument();
    expect(screen.getByLabelText('From address')).toBeInTheDocument();
    expect(screen.getByLabelText('From display name')).toBeInTheDocument();
  });

  it('has no field for a secret, and none for the kind: only the sender', async () => {
    await open();
    const labels = screen.getAllByRole('textbox').map((t) => (t as HTMLInputElement).labels?.[0]?.textContent);
    expect(labels.every((name) => ['Sender name', 'From address', 'From display name'].includes(name ?? ''))).toBe(true);
    expect(screen.queryByLabelText(/secret|password|reference/i)).not.toBeInTheDocument();
  });

  it('adds an email sender with the CSRF token and a key', async () => {
    const user = await openNotSetUp();
    await user.click(screen.getByRole('radio', { name: 'Use your own address' }));
    await user.type(screen.getByLabelText('Sender name'), 'Sample A team');
    await user.type(screen.getByLabelText('From address'), 'noreply@a.example.test');
    await user.type(screen.getByLabelText('From display name'), 'Sample A');
    await user.click(screen.getByRole('button', { name: 'Save choice' }));
    await waitFor(() => expect(seenAdminWrites).toHaveLength(1));
    expect(seenAdminWrites[0]).toMatchObject({
      method: 'POST',
      path: '/api/bff/tenant/channels',
      csrf: SAMPLE_CSRF,
      body: { kind: 'email', senderLabel: 'Sample A team', fromAddress: 'noreply@a.example.test', fromDisplayName: 'Sample A' },
    });
    expect(await screen.findByRole('status')).toHaveTextContent('Email sender saved.');
  });

  it('changes the sender that is there, by its id', async () => {
    const user = await open();
    const sender = screen.getByLabelText('Sender name');
    await user.clear(sender);
    await user.type(sender, 'Sample A service');
    await user.click(screen.getByRole('button', { name: 'Save choice' }));
    await waitFor(() => expect(seenAdminWrites).toHaveLength(1));
    expect(seenAdminWrites[0]).toMatchObject({ method: 'PUT', path: '/api/bff/tenant/channels/ch-email' });
    expect((seenAdminWrites[0]?.body as { senderLabel: string }).senderLabel).toBe('Sample A service');
  });

  it('stops using the sender, which keeps its details, with one call', async () => {
    const user = await open();
    await user.click(screen.getByRole('button', { name: 'Stop using this email sender' }));
    await waitFor(() => expect(seenAdminWrites).toHaveLength(1));
    expect(seenAdminWrites[0]?.body).toMatchObject({ kind: 'email', status: 'retired', senderLabel: 'Sample A team' });
  });

  it('needs a sender name and a valid address, in words, and sends nothing without', async () => {
    const user = await open();
    const sender = screen.getByLabelText('Sender name');
    await user.clear(sender);
    const address = screen.getByLabelText('From address');
    await user.clear(address);
    await user.type(address, 'not an address');
    await user.click(screen.getByRole('button', { name: 'Save choice' }));
    expect(await screen.findByText('Enter a sender name.', { selector: 'p' })).toBeInTheDocument();
    expect(screen.getByText('Enter an email address, for example name@example.test.', { selector: 'p' })).toBeInTheDocument();
    expect(seenAdminWrites).toEqual([]);
  });

  it('says it could not be saved on a failure', async () => {
    server.use(http.put('/api/bff/tenant/channels/ch-email', () => HttpResponse.json({}, { status: 503 })));
    const user = await open();
    await user.click(screen.getByRole('button', { name: 'Save choice' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The email sender could not be saved. Try again.');
  });

  it('says it could not load when the read fails, and has no axe violations when it loads', async () => {
    server.use(http.get('/api/bff/tenant/overview', () => HttpResponse.json({}, { status: 503 })));
    const { unmount } = render(<EmailSender />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load the email sender.');
    unmount();
    server.resetHandlers();
    await open();
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});
