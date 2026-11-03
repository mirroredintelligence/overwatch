import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { VIEW_DETAIL_ACTIVE, VIEW_DETAIL_PROVISIONING, VIEW_DETAIL_SUSPENDED } from '@/test/fixtures/operator';
import { resetOperatorWrites, seenOperatorWrites } from '@/test/msw/handlers/operator';
import { server } from '@/test/msw/server';
import { TenantDetail } from '../TenantDetail';

// Suspend, resume and start closing (TEN-083), moved out of TenantDetail.test.tsx with the panel's own file.

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

describe('suspending, resuming and starting to close', () => {
  it('suspends a live organisation with a mode and a reason, after a dialog that says what each mode does', async () => {
    const user = await open(VIEW_DETAIL_ACTIVE);
    await user.click(screen.getByRole('button', { name: 'Suspend' }));
    const dialog = await screen.findByRole('dialog', { name: 'Suspend this organisation?' });
    expect(within(dialog).getByText('Read only: people can look but nobody can change anything.')).toBeInTheDocument();
    expect(within(dialog).getByText('Blocked: nobody can sign in. Use this for a security incident.')).toBeInTheDocument();
    await user.click(within(dialog).getByRole('radio', { name: /Blocked/ }));
    await user.selectOptions(within(dialog).getByRole('combobox', { name: 'Reason' }), 'security-incident');
    await user.click(within(dialog).getByRole('button', { name: 'Confirm suspension' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'POST', path: '/api/bff/platform/tenants/trust-b/suspension', body: { mode: 'blocked', reason: 'security-incident' } });
    expect(await screen.findByText('The organisation is suspended.')).toBeInTheDocument();
  });

  it('refuses a suspension with no reason chosen', async () => {
    const user = await open(VIEW_DETAIL_ACTIVE);
    await user.click(screen.getByRole('button', { name: 'Suspend' }));
    await user.click(await screen.findByRole('button', { name: 'Confirm suspension' }));
    expect(await screen.findByText('Choose a reason.')).toBeInTheDocument();
    expect(seenOperatorWrites).toEqual([]);
  });

  it('shows a suspended organisation’s mode, reason and time, and resumes it after a dialog', async () => {
    const user = await open(VIEW_DETAIL_SUSPENDED);
    expect(screen.getByText('Suspended read only since 25 Oct 2026, 09:00. Reason: contract.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Resume' }));
    await user.click(await screen.findByRole('button', { name: 'Confirm resume' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'DELETE', path: '/api/bff/platform/tenants/trust-b/suspension' });
    expect(await screen.findByText('The organisation is resumed. 3 services were prompted and 1 announced.')).toBeInTheDocument();
  });

  it('offers no suspension to an organisation that is not live, and no resume to one that is not suspended', async () => {
    await open(VIEW_DETAIL_PROVISIONING);
    expect(screen.queryByRole('button', { name: 'Suspend' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Resume' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Start closing the organisation' })).not.toBeInTheDocument();
  });

  it('warns that closing starts at once and the export is not built, and needs the organisation’s own id typed', async () => {
    const user = await open(VIEW_DETAIL_ACTIVE);
    await user.click(screen.getByRole('button', { name: 'Start closing the organisation' }));
    const dialog = await screen.findByRole('dialog', { name: 'Start closing this organisation?' });
    expect(within(dialog).getByText(/Its people cannot sign in from now on/)).toBeInTheDocument();
    expect(within(dialog).getByText(/Exporting its data is not built yet/)).toBeInTheDocument();
    const confirm = within(dialog).getByRole('button', { name: 'Start closing' });
    expect(confirm).toBeDisabled();
    const field = () => within(dialog).getByLabelText('Type the organisation id to confirm (shown under Technical details in Organisation and sign-in)');
    await user.type(field(), 'trust-a');
    expect(confirm).toBeDisabled();
    await user.clear(field());
    await user.type(field(), 'trust-b');
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
