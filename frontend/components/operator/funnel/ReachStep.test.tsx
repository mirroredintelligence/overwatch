import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { CONSENTED, VIEW_DETAIL_PROVISIONING, VIEW_DETAIL_READY } from '@/test/fixtures/operator';
import { OPERATOR_SAMPLE_CSRF, resetOperatorWrites, seenOperatorWrites } from '@/test/msw/handlers/operator';
import { server } from '@/test/msw/server';
import { TenantDetail } from '../TenantDetail';

// Step 6 of an organisation's page (TEN-083), moved out of TenantDetail.test.tsx with the step's own file.

beforeEach(() => resetOperatorWrites());

const serveConsent = (body: unknown) => server.use(http.get('/api/bff/platform/tenants/:id/admin-consent', () => HttpResponse.json(body as Record<string, unknown>)));
function serve(detail: unknown) {
  server.use(http.get('/api/bff/platform/tenants/:id', () => HttpResponse.json(detail as Record<string, unknown>)));
}
/** Opens the page, and (when a part is named) chooses it in the task list. */
async function open(detail: unknown = VIEW_DETAIL_PROVISIONING, consent?: unknown, phase?: string) {
  serve(detail);
  if (consent !== undefined) serveConsent(consent);
  const user = userEvent.setup();
  render(<TenantDetail tenantId="trust-b" />);
  await screen.findByRole('heading', { level: 1, name: 'Sample Area B' });
  if (phase !== undefined) {
    await choose(user, phase);
    await waitFor(() => expect(screen.queryByText('Loading.')).not.toBeInTheDocument());
    // A part that is already completed shows its summary; these tests work on its steps.
    const change = screen.queryByRole('button', { name: /^Change/ });
    if (change !== null) await user.click(change);
  }
  return user;
}
const choose = (user: ReturnType<typeof userEvent.setup>, phase: string) => user.click(within(screen.getByRole('navigation', { name: 'Go live tasks' })).getByRole('link', { name: new RegExp(`^${phase}`) }));
const lastWrite = () => seenOperatorWrites[seenOperatorWrites.length - 1];
const step = (name: string) => screen.getByRole('region', { name });

describe('step 6: how people reach them', () => {
  const card = () => step('Web address and text number');

  it('sets the web address', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, undefined, 'Reach and agreements');
    await user.type(within(card()).getByLabelText('Web address'), 'tenant-b.example.test');
    await user.click(within(card()).getByRole('button', { name: 'Save web address' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'PUT', path: '/api/bff/platform/tenants/trust-b/host', csrf: OPERATOR_SAMPLE_CSRF, body: { host: 'tenant-b.example.test' } });
    expect(lastWrite()?.key).toBeTruthy();
    expect(await within(card()).findByText('Web address saved.')).toBeInTheDocument();
  });

  it('says the web address in words once set', async () => {
    await open(VIEW_DETAIL_READY, CONSENTED, 'Reach and agreements');
    expect(within(card()).getByText('Their web address is tenant-b.example.test.')).toBeInTheDocument();
  });

  it('records a text number in international form with the sender name, and refuses one that is not', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, undefined, 'Reach and agreements');
    await user.type(within(card()).getByLabelText('Text number'), '01632 960003');
    await user.type(within(card()).getByLabelText('Text account'), 'ACsample2');
    await user.type(within(card()).getByLabelText('Sender name'), 'SampleB');
    await user.click(within(card()).getByRole('button', { name: 'Record text number' }));
    expect(await within(card()).findByText('Enter the number in international form, for example +441632960003.', { selector: 'p' })).toBeInTheDocument();
    expect(seenOperatorWrites).toEqual([]);
    const number = within(card()).getByLabelText('Text number');
    await user.clear(number);
    await user.type(number, '+441632960003');
    await user.click(within(card()).getByRole('button', { name: 'Record text number' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'POST', path: '/api/bff/platform/tenants/trust-b/numbers', body: { e164: '+441632960003', accountSid: 'ACsample2', senderLabel: 'SampleB' } });
  });

  it('has no axe violations on the text number part, with a number, the shared line and the confirm step', async () => {
    const user = await open({ ...VIEW_DETAIL_PROVISIONING, sharedLine: { status: 'active', testedAt: null } }, undefined, 'Reach and agreements');
    await user.click(within(card()).getByRole('button', { name: 'Stop using +441632960002' }));
    expect(await runAxe(document.body)).toHaveNoViolations();
  });

  it('has no way to mark a number as tested by hand', async () => {
    await open(VIEW_DETAIL_PROVISIONING, undefined, 'Reach and agreements');
    expect(within(card()).queryByRole('button', { name: /Mark .* as tested/ })).not.toBeInTheDocument();
  });

  it('sends a test text from the number to the mobile typed, says the provider accepted it, and never shows the mobile again', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, undefined, 'Reach and agreements');
    const form = within(card()).getByRole('form', { name: 'Send a test text from +441632960002' });
    await user.type(within(form).getByLabelText('Mobile phone to send the test to'), '07700 900456');
    await user.click(within(form).getByRole('button', { name: 'Send a test text' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'POST', path: '/api/bff/platform/tenants/trust-b/numbers/test-text', body: { e164: '+441632960002', to: '07700 900456' } });
    expect(await within(form).findByRole('status')).toHaveTextContent('Test text sent. This line is now marked as tested because the text provider accepted the text.');
    expect(within(form).getByLabelText('Mobile phone to send the test to')).toHaveValue('');
    expect(document.body.textContent ?? '').not.toContain('07700 900456');
  });

  it('refuses a test text to something that is not a UK mobile before sending anything', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, undefined, 'Reach and agreements');
    const form = within(card()).getByRole('form', { name: 'Send a test text from +441632960002' });
    await user.type(within(form).getByLabelText('Mobile phone to send the test to'), '01632 960001');
    await user.click(within(form).getByRole('button', { name: 'Send a test text' }));
    expect(await within(form).findByText('Enter a UK mobile number, like 07700 900456.')).toBeInTheDocument();
    expect(seenOperatorWrites).toEqual([]);
  });

  it.each([
    [409, 'The organisation’s text account is not set up yet.'],
    [422, 'The text could not be sent to that number. Check it is a UK mobile number.'],
    [503, 'The text service is busy. Try again in a moment.'],
    [500, 'The test text could not be sent. Try again.'],
  ])('says in words why a test text was not sent, on a %i', async (status, words) => {
    server.use(http.post('/api/bff/platform/tenants/:id/numbers/test-text', () => HttpResponse.json({}, { status })));
    const user = await open(VIEW_DETAIL_PROVISIONING, undefined, 'Reach and agreements');
    const form = within(card()).getByRole('form', { name: 'Send a test text from +441632960002' });
    await user.type(within(form).getByLabelText('Mobile phone to send the test to'), '07700 900456');
    await user.click(within(form).getByRole('button', { name: 'Send a test text' }));
    expect(await within(form).findByRole('alert')).toHaveTextContent(words);
    expect(document.body.textContent ?? '').not.toContain('07700 900456');
  });

  it('stops using a number only after a confirm step, and says the number stays held', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, undefined, 'Reach and agreements');
    await user.click(within(card()).getByRole('button', { name: 'Stop using +441632960002' }));
    expect(seenOperatorWrites).toEqual([]);
    const confirm = within(card()).getByRole('group', { name: 'Stop using +441632960002' });
    expect(confirm).toHaveTextContent('no other organisation can take it');
    await user.click(within(confirm).getByRole('button', { name: 'Keep using it' }));
    expect(seenOperatorWrites).toEqual([]);
    await user.click(within(card()).getByRole('button', { name: 'Stop using +441632960002' }));
    await user.click(within(within(card()).getByRole('group', { name: 'Stop using +441632960002' })).getByRole('button', { name: 'Yes, stop using it' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'POST', path: '/api/bff/platform/tenants/trust-b/numbers/retire', body: { e164: '+441632960002' } });
  });

  it('says a stopped number is held, offers nothing to do with it, and counts it for nothing', async () => {
    const stopped = { ...VIEW_DETAIL_READY, numbers: VIEW_DETAIL_READY.numbers.map((n) => ({ ...n, status: 'retired' })), activation: { ready: false, blockers: ['At least one sender number active with a test text delivered'] } };
    await open(stopped, CONSENTED, 'Reach and agreements');
    expect(within(card()).getByRole('listitem')).toHaveTextContent('Stopped');
    expect(within(card()).queryByRole('button', { name: /Stop using|Send a test text/ })).not.toBeInTheDocument();
    expect(within(card()).getByText(/held for this organisation/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /^Reach and agreements/ })).toHaveTextContent('Text number not tested');
  });

  it('chooses the shared line for sending, and says plainly what it cannot do', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, undefined, 'Reach and agreements');
    expect(within(card()).getByText(/People cannot reply by text until the organisation has its own number\./)).toBeInTheDocument();
    await user.click(within(card()).getByRole('button', { name: 'Use Overwatch’s shared line (sending only)' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'POST', path: '/api/bff/platform/tenants/trust-b/numbers/shared', body: {} });
  });

  it('tests the shared line, and counts it only once a test text has been sent on it', async () => {
    const untested = { ...VIEW_DETAIL_PROVISIONING, numbers: [], sharedLine: { status: 'active', testedAt: null } };
    const user = await open(untested, undefined, 'Reach and agreements');
    expect(screen.getByRole('link', { name: /^Reach and agreements/ })).toHaveTextContent('Text number not tested');
    const form = within(card()).getByRole('form', { name: 'Send a test text from the shared line' });
    await user.type(within(form).getByLabelText('Mobile phone to send the test to'), '07700 900456');
    await user.click(within(form).getByRole('button', { name: 'Send a test text' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ path: '/api/bff/platform/tenants/trust-b/numbers/test-text', body: { to: '07700 900456' } });
    expect(lastWrite()?.body).not.toHaveProperty('e164');
  });

  it('counts a tested shared line as a tested text number', async () => {
    const tested = { ...VIEW_DETAIL_PROVISIONING, numbers: [], sharedLine: { status: 'active', testedAt: '2026-10-21T10:00:00Z' } };
    await open(tested, undefined, 'Reach and agreements');
    expect(screen.getByRole('link', { name: /^Reach and agreements/ })).toHaveTextContent('Text number tested');
  });

  it('says a web address or number another organisation holds could not be saved, on a 409', async () => {
    server.use(http.put('/api/bff/platform/tenants/:id/host', () => HttpResponse.json({ code: 'conflict' }, { status: 409 })));
    const user = await open(VIEW_DETAIL_PROVISIONING, undefined, 'Reach and agreements');
    await user.type(within(card()).getByLabelText('Web address'), 'taken.example.test');
    await user.click(within(card()).getByRole('button', { name: 'Save web address' }));
    expect(await within(card()).findByRole('alert')).toHaveTextContent('That web address is used by another organisation.');
  });

  it('says a write could not be made, and keeps what was typed', async () => {
    server.use(http.put('/api/bff/platform/tenants/:id/host', () => HttpResponse.json({}, { status: 503 })));
    const user = await open(VIEW_DETAIL_PROVISIONING, undefined, 'Reach and agreements');
    await user.type(within(card()).getByLabelText('Web address'), 'tenant-b.example.test');
    await user.click(within(card()).getByRole('button', { name: 'Save web address' }));
    expect(await within(card()).findByRole('alert')).toHaveTextContent('The web address could not be saved. Try again.');
    expect(within(card()).getByLabelText('Web address')).toHaveValue('tenant-b.example.test');
  });
});
