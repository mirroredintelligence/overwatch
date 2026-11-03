import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { CONSENTED, VIEW_DETAIL_PROVISIONING } from '@/test/fixtures/operator';
import { OPERATOR_SAMPLE_CSRF, resetOperatorWrites, seenOperatorWrites } from '@/test/msw/handlers/operator';
import { server } from '@/test/msw/server';
import { TenantDetail } from '../TenantDetail';

// Step 5 of an organisation's page (TEN-083), moved out of TenantDetail.test.tsx with the step's own file.

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
const choose = (user: ReturnType<typeof userEvent.setup>, phase: string) => user.click(within(screen.getByRole('region', { name: 'The five parts' })).getByRole('button', { name: new RegExp(`^${phase}`) }));
const lastWrite = () => seenOperatorWrites[seenOperatorWrites.length - 1];
const step = (name: string) => screen.getByRole('region', { name });

describe('step 5: who can do what', () => {
  const card = () => step('Other teams');

  it('lists the six teams in plain words with what each can do, each added to Overwatch only when it exists', async () => {
    await open(VIEW_DETAIL_PROVISIONING, undefined, 'Teams and people');
    const list = within(card()).getAllByRole('listitem');
    expect(list.map((li) => li.querySelector('strong')?.textContent)).toEqual(['Advisors', 'Shift leads', 'Clinical leads', 'Planning', 'Audit', 'Criteria owners']);
    expect(within(list[1]!).getByText('Added to Overwatch')).toBeInTheDocument();
    expect(within(list[0]!).getByText('Not added yet')).toBeInTheDocument();
    expect(list[4]).toHaveTextContent('They cannot change anything.');
  });

  it('draws the teams as a named list of tiles, each with a state a person can read', async () => {
    await open(VIEW_DETAIL_PROVISIONING, undefined, 'Teams and people');
    const list = within(card()).getByRole('list', { name: 'The other teams' });
    const tiles = Array.from(list.querySelectorAll('li'));
    expect(tiles.map((li) => li.getAttribute('data-team'))).toEqual(['advisor', 'lead', 'clinical', 'exec', 'audit', 'owner']);
    expect(tiles[1]).toHaveAttribute('data-state', 'added');
    expect(tiles[0]).toHaveAttribute('data-state', 'missing');
    expect(tiles[1]!.querySelector('[aria-hidden="true"]')).toHaveTextContent('✓');
    expect(tiles[0]!.querySelector('[aria-hidden="true"]')).toHaveTextContent('○');
  });

  it('marks a tile ticked, in words, when it is chosen, and back when it is not', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, CONSENTED, 'Teams and people');
    const tile = () => card().querySelector('[data-team="advisor"]') as HTMLElement;
    await user.click(await within(card()).findByRole('checkbox', { name: 'Advisors' }));
    expect(tile()).toHaveAttribute('data-state', 'ticked');
    expect(within(tile()).getByText('Ticked to add')).toBeInTheDocument();
    await user.click(within(card()).getByRole('checkbox', { name: 'Advisors' }));
    expect(tile()).toHaveAttribute('data-state', 'missing');
  });

  it('says the administrators’ team is the only route to administrator rights', async () => {
    await open(VIEW_DETAIL_PROVISIONING, undefined, 'Teams and people');
    expect(card()).toHaveTextContent('The administrators’ team above is the only route to administrator rights: none of these teams gives them.');
  });

  it('offers nothing to tick until their administrator has approved', async () => {
    await open(VIEW_DETAIL_PROVISIONING, undefined, 'Teams and people');
    expect(await within(card()).findByText('Teams can be added once their administrator has approved Overwatch.')).toBeInTheDocument();
    expect(within(card()).queryByRole('checkbox')).not.toBeInTheDocument();
    expect(within(card()).queryByRole('button', { name: 'Add the ticked teams' })).not.toBeInTheDocument();
  });

  it('adds the teams that were ticked, sending only roles (no name, no group id), and says so', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, CONSENTED, 'Teams and people');
    const add = await within(card()).findByRole('button', { name: 'Add the ticked teams' });
    expect(add).toBeDisabled();
    expect(within(card()).queryByRole('checkbox', { name: 'Shift leads' })).not.toBeInTheDocument();
    await user.click(within(card()).getByRole('checkbox', { name: 'Advisors' }));
    await user.click(within(card()).getByRole('checkbox', { name: 'Audit' }));
    await user.click(add);
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'POST', path: '/api/bff/platform/tenants/trust-b/entra-groups', csrf: OPERATOR_SAMPLE_CSRF, body: { roles: ['advisor', 'audit'] } });
    expect(await within(card()).findByText('The teams are added to Overwatch.')).toBeInTheDocument();
  });

  it('adds a person to an added team by email, offering only teams that exist', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, CONSENTED, 'Teams and people');
    const select = await within(card()).findByRole('combobox', { name: 'Team' });
    expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual(['Shift leads']);
    await user.type(within(card()).getByLabelText('Person’s work email'), 'sam.lead@example-trust.test');
    await user.click(within(card()).getByRole('button', { name: 'Add to team' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ path: '/api/bff/platform/tenants/trust-b/entra-groups/members', body: { role: 'lead', email: 'sam.lead@example-trust.test' } });
    expect(await within(card()).findByRole('status')).toHaveTextContent('Added to the team. The address is not kept.');
    expect(document.body.textContent ?? '').not.toContain('sam.lead@example-trust.test');
  });

  it('says a team already giving a different role was not changed, on a 409', async () => {
    server.use(http.post('/api/bff/platform/tenants/:id/entra-groups', () => HttpResponse.json({ code: 'conflict' }, { status: 409 })));
    const user = await open(VIEW_DETAIL_PROVISIONING, CONSENTED, 'Teams and people');
    await user.click(await within(card()).findByRole('checkbox', { name: 'Planning' }));
    await user.click(within(card()).getByRole('button', { name: 'Add the ticked teams' }));
    expect(await within(card()).findByRole('alert')).toHaveTextContent('A team already gives a different role. Nothing was changed.');
  });
});
