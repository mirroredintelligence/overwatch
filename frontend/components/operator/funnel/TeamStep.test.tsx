import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { CONSENTED, VIEW_DETAIL_PROVISIONING, VIEW_DETAIL_READY } from '@/test/fixtures/operator';
import { OPERATOR_SAMPLE_CSRF, resetOperatorWrites, seenOperatorWrites } from '@/test/msw/handlers/operator';
import { server } from '@/test/msw/server';
import { TenantDetail } from '../TenantDetail';

// Step 4 of an organisation's page (TEN-083), moved out of TenantDetail.test.tsx with the step's own file.

beforeEach(() => resetOperatorWrites());

type Detail = typeof VIEW_DETAIL_READY;
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
/** An element's text with its closed disclosures taken out. */
const bare = (el: HTMLElement) => {
  const clone = el.cloneNode(true) as HTMLElement;
  clone.querySelectorAll('details').forEach((d) => d.remove());
  return clone.textContent ?? '';
};
const lastWrite = () => seenOperatorWrites[seenOperatorWrites.length - 1];
const step = (name: string) => screen.getByRole('region', { name });
/** What a step shows with its closed technical details taken out. */
const headline = (name: string): string => bare(step(name));
const detailsOf = (name: string) => within(Array.from(step(name).querySelectorAll('details')).find((d) => d.querySelector('summary')?.textContent === 'Technical details') as HTMLElement);
const ready = (over: Partial<Detail> = {}): Detail => ({ ...VIEW_DETAIL_READY, ...over });

describe('step 4: their administrators’ team', () => {
  const card = () => step('Administrators’ team');
  const withAdmin = ready();

  it('offers nothing until their administrator has approved', async () => {
    await open(VIEW_DETAIL_PROVISIONING, undefined, 'Teams and people');
    expect(await within(card()).findByText('You can create their administrators’ team once their administrator has approved Overwatch.')).toBeInTheDocument();
    expect(within(card()).queryByRole('button')).not.toBeInTheDocument();
  });

  it('shows the team as one tile with what it does, "Not added yet" before it is made', async () => {
    await open(VIEW_DETAIL_PROVISIONING, undefined, 'Teams and people');
    const tile = card().querySelector('[data-team="tenant-admin"]') as HTMLElement;
    expect(tile).not.toBeNull();
    expect(tile).toHaveAttribute('data-state', 'missing');
    expect(tile).toHaveTextContent('Administrators');
    expect(tile).toHaveTextContent('Run the organisation');
    expect(within(tile).getByText('Not added yet')).toBeInTheDocument();
  });

  it('shows the tile as added once the team exists, in a word as well as a mark', async () => {
    await open(withAdmin, CONSENTED, 'Teams and people');
    await within(card()).findByText('Their administrators’ team is added to Overwatch.');
    const tile = card().querySelector('[data-team="tenant-admin"]') as HTMLElement;
    expect(tile).toHaveAttribute('data-state', 'added');
    expect(within(tile).getByText('Added to Overwatch')).toBeInTheDocument();
    expect(tile.querySelector('[aria-hidden="true"]')).toHaveTextContent('✓');
  });

  it('explains that this team is the only route to administrator rights', async () => {
    await open(VIEW_DETAIL_PROVISIONING, undefined, 'Teams and people');
    expect(card()).toHaveTextContent('The administrators’ team is the only way anyone gets administrator rights in Overwatch.');
  });

  it('creates the team once, sending no roles and no name, and lists what was made under Details', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, CONSENTED, 'Teams and people');
    await user.click(await within(card()).findByRole('button', { name: 'Create their administrators’ team' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'POST', path: '/api/bff/platform/tenants/trust-b/entra-groups', csrf: OPERATOR_SAMPLE_CSRF, body: { roles: [] } });
    expect(lastWrite()?.key).toBeTruthy();
    expect(await within(card()).findByText('Their administrators’ team is in place.')).toBeInTheDocument();
    expect(detailsOf('Administrators’ team').getByRole('row', { name: /Administrators RXX01_overwatch_tenant-admin Made now/ })).toBeInTheDocument();
    expect(headline('Administrators’ team')).not.toContain('RXX01_overwatch');
  });

  it('says the directory could not be reached, in words', async () => {
    server.use(http.post('/api/bff/platform/tenants/:id/entra-groups', () => HttpResponse.json({ code: 'transient' }, { status: 503 })));
    const user = await open(VIEW_DETAIL_PROVISIONING, CONSENTED, 'Teams and people');
    await user.click(await within(card()).findByRole('button', { name: 'Create their administrators’ team' }));
    expect(await within(card()).findByRole('alert')).toHaveTextContent('Their Microsoft account could not be reached. Try again in a minute.');
  });

  it('once the team exists, says so and adds the first administrator by email, never showing or keeping the address', async () => {
    const user = await open(withAdmin, CONSENTED, 'Teams and people');
    expect(await within(card()).findByText('Their administrators’ team is added to Overwatch.')).toBeInTheDocument();
    expect(within(card()).queryByRole('button', { name: 'Create their administrators’ team' })).not.toBeInTheDocument();
    await user.type(within(card()).getByLabelText('Administrator’s work email'), 'jane.member@example-trust.test');
    await user.click(within(card()).getByRole('button', { name: 'Add the first administrator by email' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ path: '/api/bff/platform/tenants/trust-b/entra-groups/members', body: { role: 'tenant-admin', email: 'jane.member@example-trust.test' } });
    expect(await within(card()).findByRole('status')).toHaveTextContent('Added to the team. The address is not kept.');
    expect(within(card()).getByLabelText('Administrator’s work email')).toHaveValue('');
    expect(document.body.textContent ?? '').not.toContain('jane.member@example-trust.test');
  });

  it('refuses a non-address first, and says no one has that address when their Microsoft account does not know it', async () => {
    server.use(http.post('/api/bff/platform/tenants/:id/entra-groups/members', () => HttpResponse.json({ code: 'invalid' }, { status: 400 })));
    const user = await open(withAdmin, CONSENTED, 'Teams and people');
    await user.type(await within(card()).findByLabelText('Administrator’s work email'), 'nonsense');
    await user.click(within(card()).getByRole('button', { name: 'Add the first administrator by email' }));
    expect(await within(card()).findByText('Enter the person’s work email address, for example name@organisation.nhs.uk.', { selector: 'p' })).toBeInTheDocument();
    expect(seenOperatorWrites).toEqual([]);
    await user.clear(within(card()).getByLabelText('Administrator’s work email'));
    await user.type(within(card()).getByLabelText('Administrator’s work email'), 'ghost@example-trust.test');
    await user.click(within(card()).getByRole('button', { name: 'Add the first administrator by email' }));
    expect(await within(card()).findByRole('alert')).toHaveTextContent('No one in their Microsoft accounts has that email address.');
  });

  it('has no first administrator section by another name, and no mobile invitation', async () => {
    await open(VIEW_DETAIL_PROVISIONING, undefined, 'Teams and people');
    expect(screen.queryByRole('region', { name: 'First administrator' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Send invitation' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Mobile number')).not.toBeInTheDocument();
  });

  it('has no axe violations once approved', async () => {
    await open(withAdmin, CONSENTED, 'Teams and people');
    await within(card()).findByRole('button', { name: 'Add the first administrator by email' });
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});
