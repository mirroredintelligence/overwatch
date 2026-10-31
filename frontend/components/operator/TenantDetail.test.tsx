import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { VIEW_DETAIL_ACTIVE, VIEW_DETAIL_PROVISIONING, VIEW_DETAIL_READY, VIEW_DETAIL_SUSPENDED } from '@/test/fixtures/operator';
import { OPERATOR_SAMPLE_CSRF, resetOperatorWrites, seenOperatorWrites } from '@/test/msw/handlers/operator';
import { server } from '@/test/msw/server';
import { TenantDetail } from './TenantDetail';

// One tenant's page (TEN-083): provisioning (host, numbers, references, directory, the first administrator),
// what activation waits for, and the life of the tenant (activate, suspend, resume, start closing). Every
// write is the operator's, with its CSRF token and one idempotency key per submit. A step that was done and
// not recorded by the platform chain is said so, and is never offered again. No secret is ever shown.

beforeEach(() => resetOperatorWrites());

function serve(detail: unknown) {
  server.use(http.get('/api/bff/platform/tenants/:id', () => HttpResponse.json(detail as Record<string, unknown>)));
}
async function open(detail: unknown = VIEW_DETAIL_PROVISIONING) {
  serve(detail);
  const user = userEvent.setup();
  render(<TenantDetail tenantId="trust-b" />);
  await screen.findByRole('heading', { level: 1, name: 'Sample Area B' });
  return user;
}
const lastWrite = () => seenOperatorWrites[seenOperatorWrites.length - 1];

describe('what the page shows', () => {
  it('names the tenant, its id, its status in words and its type', async () => {
    await open();
    expect(screen.getByText('trust-b')).toBeInTheDocument();
    expect(screen.getByText('Being set up')).toBeInTheDocument();
    expect(screen.getByText('Sample Area B Organisation')).toBeInTheDocument();
  });

  it('says what activation is waiting for, as a list, when a tenant is not ready', async () => {
    await open();
    const card = screen.getByRole('region', { name: 'Activation' });
    expect(within(card).getByText('Activation is unavailable until:')).toBeInTheDocument();
    expect(within(card).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['Host set', 'Number tested']);
    expect(within(card).queryByRole('button', { name: 'Activate' })).not.toBeInTheDocument();
  });

  it('shows a number with its account, its state and whether it has been tested, and never a secret', async () => {
    await open();
    const table = screen.getByRole('table', { name: 'Text numbers' });
    const row = within(table).getByRole('row', { name: /\+441632960002/ });
    expect(within(row).getByText('ACsampleaccount00000000000000000001')).toBeInTheDocument();
    expect(within(row).getByText('Not tested')).toBeInTheDocument();
    expect(within(row).getByText('Auth token held')).toBeInTheDocument();
    expect(document.body.textContent ?? '').not.toMatch(/authTokenRef|tenants\/trust-b/);
  });

  it('shows the agreement references held and the directory the administrator bound', async () => {
    await open();
    const refs = screen.getByRole('region', { name: 'Agreements' });
    expect(within(refs).getByText('DSA-2026-014')).toBeInTheDocument();
    expect(within(refs).getAllByText('Not recorded')).toHaveLength(2);
    expect(within(screen.getByRole('region', { name: 'Directory' })).getByText('11111111-1111-4111-8111-111111111111')).toBeInTheDocument();
  });

  it('says it could not find the tenant on a 404, and could not load it on another failure', async () => {
    server.use(http.get('/api/bff/platform/tenants/:id', () => HttpResponse.json({ code: 'not-found' }, { status: 404 })));
    const { unmount } = render(<TenantDetail tenantId="trust-x" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not find that tenant.');
    unmount();
    server.use(http.get('/api/bff/platform/tenants/:id', () => HttpResponse.json({}, { status: 503 })));
    render(<TenantDetail tenantId="trust-x" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load the tenant.');
  });

  it('has no axe violations', async () => {
    await open();
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});

describe('provisioning', () => {
  it('sets the address', async () => {
    const user = await open();
    await user.type(screen.getByLabelText('Address'), 'tenant-b.example.test');
    await user.click(screen.getByRole('button', { name: 'Save address' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'PUT', path: '/api/bff/platform/tenants/trust-b/host', csrf: OPERATOR_SAMPLE_CSRF, body: { host: 'tenant-b.example.test' } });
    expect(lastWrite()?.key).toBeTruthy();
    expect(await screen.findByText('Address saved.')).toBeInTheDocument();
  });

  it('records a number in E.164 form, and refuses one that is not', async () => {
    const user = await open();
    await user.type(screen.getByLabelText('Number'), '01632 960003');
    await user.type(screen.getByLabelText('Account'), 'ACsample2');
    await user.type(screen.getByLabelText('Sender name'), 'SampleB');
    await user.click(screen.getByRole('button', { name: 'Record number' }));
    expect(await screen.findByText('Enter the number in international form, for example +441632960003.', { selector: 'p' })).toBeInTheDocument();
    expect(seenOperatorWrites).toEqual([]);
    const number = screen.getByLabelText('Number');
    await user.clear(number);
    await user.type(number, '+441632960003');
    await user.click(screen.getByRole('button', { name: 'Record number' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'POST', path: '/api/bff/platform/tenants/trust-b/numbers', body: { e164: '+441632960003', accountSid: 'ACsample2', senderLabel: 'SampleB' } });
  });

  it('marks a number tested', async () => {
    const user = await open();
    await user.click(screen.getByRole('button', { name: 'Mark +441632960002 as tested' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ path: '/api/bff/platform/tenants/trust-b/numbers/tested', body: { e164: '+441632960002' } });
  });

  it('records the references that were filled in and needs at least one', async () => {
    const user = await open();
    await user.click(screen.getByRole('button', { name: 'Save references' }));
    expect(await screen.findByText('Enter at least one reference.')).toBeInTheDocument();
    expect(seenOperatorWrites).toEqual([]);
    await user.type(screen.getByLabelText('Data sharing agreement'), 'DSA-2026-015');
    await user.type(screen.getByLabelText('Clinical safety case'), 'DCB-9');
    await user.click(screen.getByRole('button', { name: 'Save references' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'PUT', path: '/api/bff/platform/tenants/trust-b/references', body: { dsaRef: 'DSA-2026-015', dcb0160Ref: 'DCB-9' } });
  });

  it('verifies the directory the administrator bound, and offers nothing when none is bound', async () => {
    const user = await open();
    await user.click(screen.getByRole('button', { name: 'Verify this directory' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ path: '/api/bff/platform/tenants/trust-b/directory/verification', body: { directoryId: '11111111-1111-4111-8111-111111111111' } });
    resetOperatorWrites();
    const { unmount } = { unmount: () => undefined };
    unmount();
    serve({ ...VIEW_DETAIL_PROVISIONING, directoryId: null });
    render(<TenantDetail tenantId="trust-b" />);
    expect(await screen.findByText('The tenant’s administrator has not bound a directory yet.')).toBeInTheDocument();
  });

  it('invites the first administrator by a UK mobile, says when the invitation ends and never shows the number again', async () => {
    const user = await open();
    await user.type(screen.getByLabelText('Mobile number'), '07700 900123');
    await user.click(screen.getByRole('button', { name: 'Send invitation' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ path: '/api/bff/platform/tenants/trust-b/admin-invitation', body: { mobile: '07700 900123' } });
    expect(await screen.findByRole('status')).toHaveTextContent('Invitation sent. It ends 1 Nov 2026, 09:00. The number is not shown again.');
    expect(screen.getByLabelText('Mobile number')).toHaveValue('');
    expect(document.body.textContent ?? '').not.toContain('07700 900123');
  });

  it('refuses a number that is not a UK mobile, and says a second open invitation is not allowed on a 409', async () => {
    const user = await open();
    await user.type(screen.getByLabelText('Mobile number'), '0161 496 0000');
    await user.click(screen.getByRole('button', { name: 'Send invitation' }));
    expect(await screen.findByText('Enter a UK mobile number, for example 07700 900123.', { selector: 'p' })).toBeInTheDocument();
    expect(seenOperatorWrites).toEqual([]);
    server.use(http.post('/api/bff/platform/tenants/:id/admin-invitation', () => HttpResponse.json({ code: 'conflict' }, { status: 409 })));
    const mobile = screen.getByLabelText('Mobile number');
    await user.clear(mobile);
    await user.type(mobile, '07700 900124');
    await user.click(screen.getByRole('button', { name: 'Send invitation' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('An invitation is already open for this tenant. Wait for it to end or be used.');
  });

  it('says a host or number another tenant holds could not be saved, on a 409', async () => {
    server.use(http.put('/api/bff/platform/tenants/:id/host', () => HttpResponse.json({ code: 'conflict' }, { status: 409 })));
    const user = await open();
    await user.type(screen.getByLabelText('Address'), 'taken.example.test');
    await user.click(screen.getByRole('button', { name: 'Save address' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('That address is held by another tenant.');
  });
});

describe('activation', () => {
  it('offers to activate a tenant that is ready, asks first, and says it is active', async () => {
    const user = await open(VIEW_DETAIL_READY);
    expect(screen.getByText('Ready to activate.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Activate' }));
    const dialog = await screen.findByRole('dialog', { name: 'Activate this tenant?' });
    await user.click(within(dialog).getByRole('button', { name: 'Confirm activation' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'POST', path: '/api/bff/platform/tenants/trust-b/activation', csrf: OPERATOR_SAMPLE_CSRF });
    expect(await screen.findByText('The tenant is active.')).toBeInTheDocument();
  });

  it('says what is still missing when the back end refuses with a 409', async () => {
    server.use(http.post('/api/bff/platform/tenants/:id/activation', () => HttpResponse.json({ code: 'business-rule' }, { status: 409 })));
    const user = await open(VIEW_DETAIL_READY);
    await user.click(screen.getByRole('button', { name: 'Activate' }));
    await user.click(await screen.findByRole('button', { name: 'Confirm activation' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The tenant cannot be activated yet. The page has been read again.');
  });

  it('can be cancelled out of', async () => {
    const user = await open(VIEW_DETAIL_READY);
    await user.click(screen.getByRole('button', { name: 'Activate' }));
    await user.click(await screen.findByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(seenOperatorWrites).toEqual([]);
  });
});

describe('suspending, resuming and starting to close', () => {
  it('suspends an active tenant with a mode and a reason, after a dialog that says what each mode does', async () => {
    const user = await open(VIEW_DETAIL_ACTIVE);
    await user.click(screen.getByRole('button', { name: 'Suspend' }));
    const dialog = await screen.findByRole('dialog', { name: 'Suspend this tenant?' });
    expect(within(dialog).getByText('Read only: people can look but nobody can change anything.')).toBeInTheDocument();
    expect(within(dialog).getByText('Blocked: nobody can sign in. Use this for a security incident.')).toBeInTheDocument();
    await user.click(within(dialog).getByRole('radio', { name: /Blocked/ }));
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Reason' }), 'security-incident');
    await user.click(within(dialog).getByRole('button', { name: 'Confirm suspension' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'POST', path: '/api/bff/platform/tenants/trust-b/suspension', body: { mode: 'blocked', reason: 'security-incident' } });
    expect(await screen.findByText('The tenant is suspended.')).toBeInTheDocument();
  });

  it('refuses a suspension with no reason chosen', async () => {
    const user = await open(VIEW_DETAIL_ACTIVE);
    await user.click(screen.getByRole('button', { name: 'Suspend' }));
    await user.click(await screen.findByRole('button', { name: 'Confirm suspension' }));
    expect(await screen.findByText('Choose a reason.')).toBeInTheDocument();
    expect(seenOperatorWrites).toEqual([]);
  });

  it('shows a suspended tenant’s mode, reason and time, and resumes it after a dialog', async () => {
    const user = await open(VIEW_DETAIL_SUSPENDED);
    expect(screen.getByText('Suspended read only since 25 Oct 2026, 09:00. Reason: contract.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Resume' }));
    await user.click(await screen.findByRole('button', { name: 'Confirm resume' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'DELETE', path: '/api/bff/platform/tenants/trust-b/suspension' });
    expect(await screen.findByText('The tenant is resumed. 3 services were prompted and 1 announced.')).toBeInTheDocument();
  });

  it('offers no suspension to a tenant that is not active, and no resume to one that is not suspended', async () => {
    await open(VIEW_DETAIL_PROVISIONING);
    expect(screen.queryByRole('button', { name: 'Suspend' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Resume' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Start closing the tenant' })).not.toBeInTheDocument();
  });

  it('warns that closing starts at once and the export is not built, and needs the tenant’s own id typed', async () => {
    const user = await open(VIEW_DETAIL_ACTIVE);
    await user.click(screen.getByRole('button', { name: 'Start closing the tenant' }));
    const dialog = await screen.findByRole('dialog', { name: 'Start closing this tenant?' });
    expect(within(dialog).getByText(/Its people cannot sign in from now on/)).toBeInTheDocument();
    expect(within(dialog).getByText(/Exporting its data is not built yet/)).toBeInTheDocument();
    const confirm = within(dialog).getByRole('button', { name: 'Start closing' });
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByLabelText('Type the tenant id to confirm'), 'trust-a');
    expect(confirm).toBeDisabled();
    await user.clear(within(dialog).getByLabelText('Type the tenant id to confirm'));
    await user.type(within(dialog).getByLabelText('Type the tenant id to confirm'), 'trust-b');
    expect(confirm).toBeEnabled();
    await user.click(confirm);
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'POST', path: '/api/bff/platform/tenants/trust-b/offboarding', body: { confirm: 'trust-b' } });
    expect(await screen.findByText('Closing has started. The notice ends 29 Nov 2026, 09:00.')).toBeInTheDocument();
  });
});

describe('a step that was done and could not be recorded', () => {
  it('says so, as an alert, and does not offer the step again', async () => {
    server.use(http.post('/api/bff/platform/tenants/:id/suspension', () => HttpResponse.json({ mode: 'read-only', recorded: false })));
    const user = await open(VIEW_DETAIL_ACTIVE);
    await user.click(screen.getByRole('button', { name: 'Suspend' }));
    await user.selectOptions(await screen.findByRole('combobox', { name: 'Reason' }), 'contract');
    await user.click(screen.getByRole('button', { name: 'Confirm suspension' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The step was done, but the platform record could not be written. Do not repeat it. Tell the person who looks after the platform record.');
  });
});

describe('failures', () => {
  it('says a write could not be made, and keeps what was typed', async () => {
    server.use(http.put('/api/bff/platform/tenants/:id/host', () => HttpResponse.json({}, { status: 503 })));
    const user = await open();
    await user.type(screen.getByLabelText('Address'), 'tenant-b.example.test');
    await user.click(screen.getByRole('button', { name: 'Save address' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The address could not be saved. Try again.');
    expect(screen.getByLabelText('Address')).toHaveValue('tenant-b.example.test');
  });
});
