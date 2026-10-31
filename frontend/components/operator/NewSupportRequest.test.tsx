import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { VIEW_TENANTS_SUPPORT } from '@/test/fixtures/operator';
import { OPERATOR_SAMPLE_CSRF, resetOperatorWrites, seenOperatorWrites } from '@/test/msw/handlers/operator';
import { server } from '@/test/msw/server';
import { NewSupportRequest } from './NewSupportRequest';

// Asking to look into a tenant (TEN-083, DEC-1003): one active tenant, a reason code, and a plain sentence
// that holds no name, number, postcode or patient. The restricted alphabet and the six-digit limit are said
// before the call and checked again by the back end.

beforeEach(() => {
  resetOperatorWrites();
  server.use(http.get('/api/bff/platform/tenants', () => HttpResponse.json(VIEW_TENANTS_SUPPORT)));
});

async function open(initial?: string) {
  const user = userEvent.setup();
  render(<NewSupportRequest initialTenant={initial} />);
  await screen.findByRole('option', { name: 'Sample Area A' });
  return user;
}
const REASON = 'The board shows a service twice';

describe('NewSupportRequest', () => {
  it('offers the active tenants only, by name, and the six reasons in words', async () => {
    await open();
    const tenants = within(screen.getByRole('combobox', { name: 'Tenant' })).getAllByRole('option').map((o) => o.textContent);
    expect(tenants).toEqual(['Choose a tenant', 'Sample Area A']);
    const reasons = within(screen.getByRole('combobox', { name: 'Type of problem' })).getAllByRole('option').map((o) => o.textContent);
    expect(reasons).toEqual(['Security incident', 'Clinical safety', 'Service fault', 'Configuration', 'A user asked for help', 'Other']);
  });

  it('chooses the tenant it was sent from, when that one is active', async () => {
    await open('trust-a');
    expect(screen.getByRole('combobox', { name: 'Tenant' })).toHaveValue('trust-a');
  });

  it('says how to write the reason, and what not to put in it', async () => {
    await open();
    expect(screen.getByText('Write a plain sentence of 10 to 200 characters. Do not put in a name, a phone number, a postcode or anything about a patient.')).toBeInTheDocument();
  });

  it('sends the request to the tenant’s path, with the reason and the reference, and says what happens next', async () => {
    const user = await open();
    await user.selectOptions(screen.getByRole('combobox', { name: 'Tenant' }), 'trust-a');
    await user.type(screen.getByLabelText('Reason in a sentence'), REASON);
    await user.type(screen.getByLabelText('Help-desk reference'), 'HD-1042');
    await user.click(screen.getByRole('button', { name: 'Send the request' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    const write = seenOperatorWrites[0]!;
    expect(write).toMatchObject({ method: 'POST', path: '/api/bff/platform/tenants/trust-a/support-tickets', csrf: OPERATOR_SAMPLE_CSRF, body: { reasonCode: 'service-fault', reason: REASON, reference: 'HD-1042' } });
    expect(write.key).toBeTruthy();
    const done = await screen.findByRole('status');
    expect(done).toHaveTextContent('Request sent. The tenant’s administrator will see it and, if they agree, give you a code.');
    expect(within(done).getByRole('link', { name: 'See the request' })).toHaveAttribute('href', '/operator/support/tickets/tkt-1');
  });

  it('leaves the reference out when it is empty', async () => {
    const user = await open('trust-a');
    await user.type(screen.getByLabelText('Reason in a sentence'), REASON);
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
    await user.type(screen.getByLabelText('Reason in a sentence'), reason);
    await user.click(screen.getByRole('button', { name: 'Send the request' }));
    expect(await screen.findByText(message, { selector: 'p' })).toBeInTheDocument();
    expect(seenOperatorWrites).toEqual([]);
  });

  it('asks for a tenant, and refuses a reference that is not letters, digits and hyphens', async () => {
    const user = await open();
    await user.type(screen.getByLabelText('Reason in a sentence'), REASON);
    await user.type(screen.getByLabelText('Help-desk reference'), 'HD 1042!');
    await user.click(screen.getByRole('button', { name: 'Send the request' }));
    expect(await screen.findByText('Choose a tenant.', { selector: 'p' })).toBeInTheDocument();
    expect(screen.getByText('Use letters, digits and hyphens only, up to 32.', { selector: 'p' })).toBeInTheDocument();
    expect(seenOperatorWrites).toEqual([]);
  });

  it('says there is already a request open on a 409, and that the tenant cannot be asked on a 404', async () => {
    const user = await open('trust-a');
    await user.type(screen.getByLabelText('Reason in a sentence'), REASON);
    server.use(http.post('/api/bff/platform/tenants/:id/support-tickets', () => HttpResponse.json({ code: 'conflict' }, { status: 409 })));
    await user.click(screen.getByRole('button', { name: 'Send the request' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('You already have a request open for this tenant. Finish it or let it lapse first.');
    server.use(http.post('/api/bff/platform/tenants/:id/support-tickets', () => HttpResponse.json({ code: 'not-found' }, { status: 404 })));
    await user.click(screen.getByRole('button', { name: 'Send the request' }));
    expect(await screen.findByText('That tenant cannot be asked now. It may not be active.')).toBeInTheDocument();
  });

  it('says it could not load the tenants, and has no axe violations when it loads', async () => {
    server.use(http.get('/api/bff/platform/tenants', () => HttpResponse.json({}, { status: 503 })));
    const { unmount } = render(<NewSupportRequest />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load the tenants.');
    unmount();
    server.use(http.get('/api/bff/platform/tenants', () => HttpResponse.json(VIEW_TENANTS_SUPPORT)));
    await open();
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});
