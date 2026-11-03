import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { VIEW_TENANTS_SUPPORT } from '@/test/fixtures/operator';
import { OPERATOR_SAMPLE_CSRF, resetOperatorWrites, seenOperatorWrites } from '@/test/msw/handlers/operator';
import { server } from '@/test/msw/server';
import { NewSupportRequest } from './NewSupportRequest';

// Asking to look into an organisation (TEN-083, DEC-1003, board O5): a right-hand sheet over the page, a dialog
// with a focus trap and Escape. One live organisation, a reason code, and a plain sentence that holds no name,
// number, postcode or patient. The restricted alphabet and the six-digit limit are said before the call and
// checked again by the back end.

const push = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));

beforeEach(() => {
  push.mockReset();
  resetOperatorWrites();
  server.use(http.get('/api/bff/platform/tenants', () => HttpResponse.json(VIEW_TENANTS_SUPPORT)));
});

async function open(initial?: string) {
  const user = userEvent.setup();
  render(<NewSupportRequest initialTenant={initial} />);
  await screen.findByRole('radio', { name: 'Sample Area A' });
  return user;
}
const REASON = 'The board shows a service twice';
const WHY = 'Why, in a sentence';

describe('the sheet', () => {
  it('is a dialog named Ask for access, with the words that say nothing opens until the administrator approves', async () => {
    await open();
    const dialog = screen.getByRole('dialog', { name: 'Ask for access' });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(within(dialog).getByRole('heading', { level: 2, name: 'Ask for access' })).toBeInTheDocument();
    expect(within(dialog).getByText('Choose a live organisation. Nothing opens until its administrator approves.')).toBeInTheDocument();
  });

  it('puts focus inside, closes on Escape and on Close and Cancel, and sends nothing', async () => {
    const user = await open();
    const dialog = screen.getByRole('dialog', { name: 'Ask for access' });
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
    await user.keyboard('{Escape}');
    expect(push).toHaveBeenLastCalledWith('/operator/support');
    await user.click(screen.getByRole('button', { name: 'Close' }));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(push).toHaveBeenCalledTimes(3);
    expect(seenOperatorWrites).toEqual([]);
  });

  it('keeps Tab and Shift+Tab inside the sheet', async () => {
    const user = await open();
    const dialog = screen.getByRole('dialog', { name: 'Ask for access' });
    const cancel = screen.getByRole('button', { name: 'Cancel' });
    cancel.focus();
    await user.tab();
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Close' }));
    await user.tab({ shift: true });
    expect(document.activeElement).toBe(cancel);
  });
});

describe('NewSupportRequest', () => {
  it('offers the live organisations only, by name, as a group of choices, and the six reasons in words', async () => {
    await open();
    const group = screen.getByRole('radiogroup', { name: 'Organisation' });
    expect(within(group).getAllByRole('radio').map((r) => r.getAttribute('value'))).toEqual(['trust-a']);
    expect(within(group).getByText('Live')).toBeInTheDocument();
    const reasons = within(screen.getByRole('combobox', { name: 'Type of problem' })).getAllByRole('option').map((o) => o.textContent);
    expect(reasons).toEqual(['Security incident', 'Clinical safety', 'Service fault', 'Configuration', 'A user asked for help', 'Other']);
  });

  it('chooses the organisation it was sent from, when that one is live', async () => {
    await open('trust-a');
    expect(screen.getByRole('radio', { name: 'Sample Area A' })).toBeChecked();
  });

  it('says how to write the reason, and what not to put in it', async () => {
    await open();
    expect(screen.getByText('Write a plain sentence of 10 to 200 characters. Do not put in a name, a phone number, a postcode or anything about a patient.')).toBeInTheDocument();
  });

  it('sends the request to the organisation’s path, with the reason and the reference, and says what happens next', async () => {
    const user = await open();
    await user.click(screen.getByRole('radio', { name: 'Sample Area A' }));
    await user.type(screen.getByLabelText(WHY), REASON);
    await user.type(screen.getByLabelText('Help-desk reference'), 'HD-1042');
    await user.click(screen.getByRole('button', { name: 'Send the request' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    const write = seenOperatorWrites[0]!;
    expect(write).toMatchObject({ method: 'POST', path: '/api/bff/platform/tenants/trust-a/support-tickets', csrf: OPERATOR_SAMPLE_CSRF, body: { reasonCode: 'service-fault', reason: REASON, reference: 'HD-1042' } });
    expect(write.key).toBeTruthy();
    const done = await screen.findByRole('status');
    expect(done).toHaveTextContent('Request sent. The organisation’s administrator will see it and, if they agree, give you a code.');
    expect(within(done).getByRole('link', { name: 'See the request' })).toHaveAttribute('href', '/operator/support/tickets/tkt-1');
  });

  it('says it is sending while the call is out, and cannot be pressed twice', async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.post('/api/bff/platform/tenants/:id/support-tickets', async () => {
        await gate;
        return HttpResponse.json({}, { status: 503 });
      }),
    );
    const user = await open('trust-a');
    await user.type(screen.getByLabelText(WHY), REASON);
    await user.click(screen.getByRole('button', { name: 'Send the request' }));
    expect(await screen.findByText('Sending the request.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Send the request' })).toBeDisabled();
    release();
    expect(await screen.findByRole('alert')).toHaveTextContent('The request could not be sent. Try again.');
    expect(screen.queryByText('Sending the request.')).not.toBeInTheDocument();
  });

  it('leaves the reference out when it is empty', async () => {
    const user = await open('trust-a');
    await user.type(screen.getByLabelText(WHY), REASON);
    await user.click(screen.getByRole('button', { name: 'Send the request' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(seenOperatorWrites[0]?.body).toEqual({ reasonCode: 'service-fault', reason: REASON });
  });

  it.each([
    ['too short', 'short', 'Write at least 10 characters.'],
    ['a character that is not allowed', 'Please call <b>me</b> about the board', 'Use letters, digits and . , \' & ( ) + - only.'],
    ['more than six digits', 'Service 1234567 shows twice today', 'Leave out long numbers: use at most six digits.'],
  ])('refuses a reason that is %s, in words next to the field, and sends nothing', async (_name, reason, message) => {
    const user = await open('trust-a');
    await user.type(screen.getByLabelText(WHY), reason);
    await user.click(screen.getByRole('button', { name: 'Send the request' }));
    expect(await screen.findByText(message, { selector: 'p' })).toBeInTheDocument();
    expect(seenOperatorWrites).toEqual([]);
  });

  it('asks for an organisation, summarises the problems, and refuses a reference that is not letters, digits and hyphens', async () => {
    const user = await open();
    await user.type(screen.getByLabelText(WHY), REASON);
    await user.type(screen.getByLabelText('Help-desk reference'), 'HD 1042!');
    await user.click(screen.getByRole('button', { name: 'Send the request' }));
    expect(await screen.findByText('Choose an organisation.', { selector: 'p' })).toBeInTheDocument();
    expect(screen.getByText('Use letters, digits and hyphens only, up to 32.', { selector: 'p' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'There are 2 problems' })).toBeInTheDocument();
    expect(seenOperatorWrites).toEqual([]);
  });

  it('says there is already a request open on a 409, and that the organisation cannot be asked on a 404', async () => {
    const user = await open('trust-a');
    await user.type(screen.getByLabelText(WHY), REASON);
    server.use(http.post('/api/bff/platform/tenants/:id/support-tickets', () => HttpResponse.json({ code: 'conflict' }, { status: 409 })));
    await user.click(screen.getByRole('button', { name: 'Send the request' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('You already have a request open for this organisation. Finish it or let it lapse first.');
    server.use(http.post('/api/bff/platform/tenants/:id/support-tickets', () => HttpResponse.json({ code: 'not-found' }, { status: 404 })));
    await user.click(screen.getByRole('button', { name: 'Send the request' }));
    expect(await screen.findByText('That organisation cannot be asked now. It may not be live.')).toBeInTheDocument();
  });

  it('says there is no live organisation to ask when there is none', async () => {
    server.use(http.get('/api/bff/platform/tenants', () => HttpResponse.json({ tenants: [] })));
    render(<NewSupportRequest />);
    expect(await screen.findByText('No organisation is live yet, so there is no one to ask.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Send the request' })).not.toBeInTheDocument();
  });

  it('says it could not load the organisations, offers another try, and has no axe violations when it loads', async () => {
    server.use(http.get('/api/bff/platform/tenants', () => HttpResponse.json({}, { status: 503 })));
    const { unmount } = render(<NewSupportRequest />);
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('We could not load the organisations.');
    expect(within(alert).getByRole('button', { name: 'Try again' })).toBeInTheDocument();
    unmount();
    server.use(http.get('/api/bff/platform/tenants', () => HttpResponse.json(VIEW_TENANTS_SUPPORT)));
    await open();
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});
