import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { CONSENTED, VIEW_DETAIL_PROVISIONING, VIEW_DETAIL_READY } from '@/test/fixtures/operator';
import { resetOperatorWrites, seenOperatorWrites } from '@/test/msw/handlers/operator';
import { server } from '@/test/msw/server';
import { TenantDetail } from '../TenantDetail';

// Step 2 of an organisation's page (TEN-083), moved out of TenantDetail.test.tsx with the step's own file.

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

describe('step 2: connect their sign-in', () => {
  it('confirms the Microsoft account the organisation named, with one button', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, undefined, 'Organisation and sign-in');
    await user.click(within(step('Connect their Microsoft work accounts')).getByRole('button', { name: 'Confirm this is their Microsoft account' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'POST', path: '/api/bff/platform/tenants/trust-b/directory/verification', body: { directoryId: '11111111-1111-4111-8111-111111111111' } });
    expect(lastWrite()?.key).toBeTruthy();
  });

  it('says the connection in words once confirmed, and offers no button', async () => {
    await open(VIEW_DETAIL_READY, CONSENTED, 'Organisation and sign-in');
    const card = step('Connect their Microsoft work accounts');
    expect(within(card).getByText('Connected to Sample Area B’s Microsoft accounts.')).toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: 'Confirm this is their Microsoft account' })).not.toBeInTheDocument();
  });

  it('says nothing is connected when no account is named, and offers no button', async () => {
    await open({ ...VIEW_DETAIL_PROVISIONING, directoryId: null, bindings: [], roleMappings: [] }, undefined, 'Organisation and sign-in');
    const card = step('Connect their Microsoft work accounts');
    expect(within(card).getByText('No Microsoft account is connected yet.', { selector: 'p' })).toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: 'Confirm this is their Microsoft account' })).not.toBeInTheDocument();
  });

  it('looks up their Microsoft account from the domain as a card, and says whether it is the one named, and saves nothing', async () => {
    server.use(http.get('/api/bff/platform/directory-lookup', () => HttpResponse.json({ domain: 'example-trust.test', directoryId: '11111111-1111-4111-8111-111111111111' })));
    const user = await open(VIEW_DETAIL_PROVISIONING, undefined, 'Organisation and sign-in');
    const card = step('Connect their Microsoft work accounts');
    await user.type(within(card).getByLabelText('Their email domain'), 'example-trust.test');
    await user.click(within(card).getByRole('button', { name: 'Look up their Microsoft account' }));
    const found = await waitFor(() => {
      const el = card.querySelector('[data-el="OP-TENANT-DOMAIN-CARD"]');
      expect(el).not.toBeNull();
      return el as HTMLElement;
    });
    expect(found).toHaveTextContent('Found a Microsoft account for example-trust.test.');
    expect(found).toHaveTextContent('It is the same one that is connected here.');
    expect(seenOperatorWrites).toEqual([]);
  });

  it('says when the account found is not the one named, and when none was found', async () => {
    server.use(http.get('/api/bff/platform/directory-lookup', () => HttpResponse.json({ domain: 'other.test', directoryId: '99999999-9999-4999-8999-999999999999' })));
    const user = await open(VIEW_DETAIL_PROVISIONING, undefined, 'Organisation and sign-in');
    const card = step('Connect their Microsoft work accounts');
    await user.type(within(card).getByLabelText('Their email domain'), 'other.test');
    await user.click(within(card).getByRole('button', { name: 'Look up their Microsoft account' }));
    expect(await within(card).findByText('It is not the one that is connected here. Check before you confirm.')).toBeInTheDocument();
    server.use(http.get('/api/bff/platform/directory-lookup', () => HttpResponse.json({ domain: 'nowhere.test', directoryId: null })));
    await user.click(within(card).getByRole('button', { name: 'Look up their Microsoft account' }));
    expect(await within(card).findByText('No Microsoft account was found for nowhere.test. Ask the organisation which one they use.')).toBeInTheDocument();
  });
});

// The board (O4, part 1): one row for the directory, in the part's states.
describe('step 2: the directory row for each state', () => {
  const rowOf = (card: HTMLElement, title: string) => within(card).getByText(title).closest('[data-state]') as HTMLElement;
  const card = () => step('Connect their Microsoft work accounts');

  it('not started: a dashed row that says nothing is connected, with the word To do', async () => {
    await open({ ...VIEW_DETAIL_PROVISIONING, directoryId: null, bindings: [], roleMappings: [] }, undefined, 'Organisation and sign-in');
    const row = rowOf(card(), 'Microsoft work accounts not connected');
    expect(row).toHaveAttribute('data-state', 'todo');
    expect(within(row).getByText('To do')).toBeInTheDocument();
  });

  it('waiting for the operator: an amber row that says it is named and not yet confirmed, and the one button', async () => {
    await open(VIEW_DETAIL_PROVISIONING, undefined, 'Organisation and sign-in');
    const row = rowOf(card(), 'Microsoft work accounts named');
    expect(row).toHaveAttribute('data-state', 'waiting');
    expect(within(row).getByText('Waiting for you')).toBeInTheDocument();
    expect(within(card()).getByRole('button', { name: 'Confirm this is their Microsoft account' })).toBeInTheDocument();
  });

  it('done: a checked row with the day it was confirmed, and no directory id on its face', async () => {
    await open(VIEW_DETAIL_READY, CONSENTED, 'Organisation and sign-in');
    const row = rowOf(card(), 'Microsoft work accounts connected');
    expect(row).toHaveAttribute('data-state', 'done');
    expect(row).toHaveTextContent(/Confirmed on 21 Oct 2026/);
    expect(within(row).getByText('Done')).toBeInTheDocument();
    expect(row).not.toHaveTextContent('11111111-1111-4111-8111-111111111111');
  });

  it('error on the action: the part stays open, the button stays, and the problem is said in words', async () => {
    server.use(http.post('/api/bff/platform/tenants/:id/directory/verification', () => HttpResponse.json({ code: 'failed' }, { status: 500 })));
    const user = await open(VIEW_DETAIL_PROVISIONING, undefined, 'Organisation and sign-in');
    await user.click(within(card()).getByRole('button', { name: 'Confirm this is their Microsoft account' }));
    expect(await within(card()).findByRole('alert')).toHaveTextContent('It could not be confirmed. Try again.');
    expect(within(card()).getByRole('button', { name: 'Confirm this is their Microsoft account' })).toBeEnabled();
    expect(rowOf(card(), 'Microsoft work accounts named')).toHaveAttribute('data-state', 'waiting');
  });

  it('keeps the domain check closed under its own disclosure, and the identifiers under technical details', async () => {
    await open(VIEW_DETAIL_PROVISIONING, undefined, 'Organisation and sign-in');
    const check = within(card()).getByText('Check an email domain').closest('details') as HTMLElement;
    expect(check).not.toHaveAttribute('open');
    const tech = within(card()).getByText('Technical details').closest('details') as HTMLElement;
    expect(within(tech).getByText('11111111-1111-4111-8111-111111111111')).toBeInTheDocument();
  });

  it('has no accessibility violations', async () => {
    await open(VIEW_DETAIL_PROVISIONING, undefined, 'Organisation and sign-in');
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});
