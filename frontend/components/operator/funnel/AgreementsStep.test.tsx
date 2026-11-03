import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { CONSENTED, VIEW_DETAIL_PROVISIONING, VIEW_DETAIL_READY } from '@/test/fixtures/operator';
import { resetOperatorWrites, seenOperatorWrites } from '@/test/msw/handlers/operator';
import { server } from '@/test/msw/server';
import { TenantDetail } from '../TenantDetail';

// Step 7 of an organisation's page (TEN-083), moved out of TenantDetail.test.tsx with the step's own file.

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

describe('step 7: agreements', () => {
  it('says how many of the three are recorded, and that they are recommended, not required', async () => {
    await open(VIEW_DETAIL_PROVISIONING, undefined, 'Reach and agreements');
    const card = step('Agreements (recommended)');
    const row = within(card).getByRole('group', { name: 'Agreements, recommended, not required' });
    expect(within(row).getByText('Agreements')).toBeInTheDocument();
    expect(within(row).getByText('recommended, not required')).toBeInTheDocument();
    expect(within(row).getByText('Data sharing, privacy impact, clinical safety')).toBeInTheDocument();
    expect(within(row).getByText('1 of 3 recorded')).toBeInTheDocument();
    expect(row.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
  });

  it('says all three are recorded when they are', async () => {
    await open(VIEW_DETAIL_READY, CONSENTED, 'Reach and agreements');
    const row = within(step('Agreements (recommended)')).getByRole('group', { name: 'Agreements, recommended, not required' });
    expect(within(row).getByText('3 of 3 recorded')).toBeInTheDocument();
  });

  it('says none are recorded when none are', async () => {
    const none = { ...VIEW_DETAIL_PROVISIONING, tenant: { ...VIEW_DETAIL_PROVISIONING.tenant, references: { dsa: null, dpia: null, dcb0160: null } } };
    await open(none, undefined, 'Reach and agreements');
    const row = within(step('Agreements (recommended)')).getByRole('group', { name: 'Agreements, recommended, not required' });
    expect(within(row).getByText('0 of 3 recorded')).toBeInTheDocument();
  });

  it('records the references that were filled in and needs at least one', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, undefined, 'Reach and agreements');
    const card = step('Agreements (recommended)');
    await user.click(within(card).getByRole('button', { name: 'Save agreements' }));
    expect(await within(card).findByText('Enter at least one reference.')).toBeInTheDocument();
    expect(seenOperatorWrites).toEqual([]);
    await user.type(within(card).getByLabelText('Data sharing agreement'), 'DSA-2026-015');
    await user.type(within(card).getByLabelText('Clinical safety case'), 'DCB-9');
    await user.click(within(card).getByRole('button', { name: 'Save agreements' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'PUT', path: '/api/bff/platform/tenants/trust-b/references', body: { dsaRef: 'DSA-2026-015', dcb0160Ref: 'DCB-9' } });
    expect(await within(card).findByText('Agreements saved.')).toBeInTheDocument();
  });
});
