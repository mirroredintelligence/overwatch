import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { CONSENTED, VIEW_DETAIL_ACTIVE, VIEW_DETAIL_PROVISIONING, VIEW_DETAIL_READY } from '@/test/fixtures/operator';
import { OPERATOR_SAMPLE_CSRF, resetOperatorWrites, seenOperatorWrites } from '@/test/msw/handlers/operator';
import { server } from '@/test/msw/server';
import { TenantDetail } from '../TenantDetail';

// The Go live step of an organisation's page (TEN-083), moved out of TenantDetail.test.tsx with the step's own file.

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
const ready = (over: Partial<Detail> = {}): Detail => ({ ...VIEW_DETAIL_READY, ...over });

describe('Go live', () => {
  it('shows the button only when everything is done and the back end agrees, and asks first', async () => {
    const user = await open(VIEW_DETAIL_READY, CONSENTED);
    await within(step('Go live')).findByRole('button', { name: 'Go live' });
    expect(within(step('Go live')).getByText('Everything is ready. Once it is live, their people can sign in.')).toBeInTheDocument();
    expect(screen.getByText('4 of 5 parts completed')).toBeInTheDocument();
    await user.click(within(step('Go live')).getByRole('button', { name: 'Go live' }));
    const dialog = await screen.findByRole('dialog', { name: 'Go live with this organisation?' });
    await user.click(within(dialog).getByRole('button', { name: 'Yes, go live' }));
    await waitFor(() => expect(seenOperatorWrites).toHaveLength(1));
    expect(lastWrite()).toMatchObject({ method: 'POST', path: '/api/bff/platform/tenants/trust-b/activation', csrf: OPERATOR_SAMPLE_CSRF });
    expect(await screen.findByText('The organisation is live.')).toBeInTheDocument();
  });

  it('has the one primary button on the Go live part when it is ready, and none that looks blocked', async () => {
    await open(VIEW_DETAIL_READY, CONSENTED);
    const panel = step('Go live');
    expect(await within(panel).findByRole('button', { name: 'Go live' })).toBeEnabled();
    expect(within(panel).getAllByRole('button')).toHaveLength(1);
  });

  it('has no button, and a short list of what is left by part with a count, while a step is not done', async () => {
    await open(VIEW_DETAIL_PROVISIONING, undefined, 'Go live');
    const card = step('Go live');
    expect(within(card).queryByRole('button', { name: 'Go live' })).not.toBeInTheDocument();
    const left = within(card).getByRole('list', { name: 'Still to do' });
    const lines = within(left).getAllByRole('listitem').map((li) => li.textContent);
    expect(lines).toEqual(['Organisation and sign-in 1 thing left', 'Administrator approval 1 thing left', 'Teams and people 1 thing left', 'Reach and agreements 2 things left']);
  });

  it('never lists the agreements as left, and says they are recommended', async () => {
    await open(VIEW_DETAIL_PROVISIONING, undefined, 'Go live');
    const card = step('Go live');
    expect(bare(card)).not.toMatch(/agreements? (is|are) not|Agreements \(recommended\)/i);
    await waitFor(() => expect(screen.queryByText('Loading.')).not.toBeInTheDocument());
    expect(document.body.textContent ?? '').toContain('Agreements (recommended) 1 of 3');
  });

  it('can go live with no agreement recorded', async () => {
    const none = { dsa: null, dpia: null, dcb0160: null };
    await open({ ...VIEW_DETAIL_READY, tenant: { ...VIEW_DETAIL_READY.tenant, references: none } }, CONSENTED, 'Go live');
    expect(await within(step('Go live')).findByRole('button', { name: 'Go live' })).toBeEnabled();
  });

  it('takes the operator to a part from the list of what is left', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, undefined, 'Go live');
    await user.click(within(within(step('Go live')).getByRole('list', { name: 'Still to do' })).getByRole('link', { name: 'Reach and agreements' }));
    expect(screen.getByRole('heading', { level: 2, name: 'Reach and agreements' })).toHaveFocus();
  });

  it.each<[string, () => Detail, unknown]>([
    ['the sign-in is not confirmed', () => ready({ bindings: [{ directoryId: '11111111-1111-4111-8111-111111111111', status: 'pending', verifiedAt: null }] }), CONSENTED],
    ['their administrator has not approved', () => VIEW_DETAIL_READY, { invitation: null }],
    ['their administrators’ team is missing', () => ready({ roleMappings: [{ groupObjectId: '22222222-2222-4222-8222-222222222222', role: 'lead', status: 'active' }] }), CONSENTED],
    ['no other team is added', () => ready({ roleMappings: [{ groupObjectId: '33333333-3333-4333-8333-333333333333', role: 'tenant-admin', status: 'active' }] }), CONSENTED],
    ['the web address is not set', () => ready({ host: null }), CONSENTED],
    ['no number has been tested', () => ready({ numbers: VIEW_DETAIL_READY.numbers.map((n) => ({ ...n, testedAt: null })) }), CONSENTED],
  ])('has no Go live button when %s, and lists what is left', async (_name, make, consent) => {
    await open(make(), consent, 'Go live');
    await screen.findByText(/parts completed/);
    await waitFor(() => expect(screen.queryByText('Loading.')).not.toBeInTheDocument());
    expect(screen.queryByRole('button', { name: 'Go live' })).not.toBeInTheDocument();
    expect(within(step('Go live')).getByRole('list', { name: 'Still to do' })).toBeInTheDocument();
  });

  it('does not make the button look blocked by what only their administrators can do: it says Overwatch will open it', async () => {
    await open(ready({ activation: { ready: false, blockers: ['Area districts set', 'Network agreement accepted'] } }), CONSENTED, 'Go live');
    const card = step('Go live');
    await within(card).findByText('Everything you have to do is done.');
    expect(within(card).queryByRole('list', { name: 'Still to do' })).not.toBeInTheDocument();
    expect(within(card).queryByRole('button')).not.toBeInTheDocument();
    const theirs = within(card).getByRole('list', { name: 'Their administrators finish these' });
    expect(within(theirs).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['To doSet the area’s districts', 'To doAccept the network agreement']);
    expect(within(card).getByRole('heading', { name: 'Their administrators finish these after they sign in' })).toBeInTheDocument();
    expect(within(card).getByText('Overwatch will make Go live available when these are done.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /^Go live/ })).toHaveTextContent('Waiting for them');
  });

  it('never shows the back end’s own blocker text, merges blockers that say the same thing, and keeps their administrators’ items apart', async () => {
    const blockers = [
      'Configuration version approved',
      'Time zone set',
      'At least one sender number active with a test text delivered',
      'Email sender verified',
      'Tenant administrator group made and mapped',
      'Sign-in directory bound and verified',
      'At least one role mapping',
      'Support contacts set: coordination phone and clinical safety officer',
      'Retention set for every data class',
      'System, referral system and coordination team names set',
      'Area districts set',
      'Network agreement accepted',
      'Host set',
      'Something nobody has thought of',
    ];
    await open({ ...VIEW_DETAIL_PROVISIONING, activation: { ready: false, blockers } }, undefined, 'Go live');
    const text = document.body.textContent ?? '';
    for (const blocker of blockers) expect(text).not.toContain(blocker);
    expect(text).not.toContain('Number tested');
    const card = step('Go live');
    const lines = within(within(card).getByRole('list', { name: 'Still to do' })).getAllByRole('listitem').map((li) => li.textContent);
    expect(lines).toEqual([
      'Organisation and sign-in 2 things left',
      'Administrator approval 2 things left',
      'Teams and people 2 things left',
      'Reach and agreements 2 things left',
      'Go live 1 thing left',
    ]);
    const theirs = within(within(card).getByRole('list', { name: 'Their administrators finish these' })).getAllByRole('listitem').map((li) => li.textContent);
    expect(theirs).toEqual(['To doApprove their settings', 'To doSet the support contacts', 'To doSet how long records are kept', 'To doSet the names they use for their systems', 'To doSet the area’s districts', 'To doAccept the network agreement']);
    expect(text).not.toContain('No team has been given anything to do yet');
  });

  it('says what is still missing when the back end refuses with a 409', async () => {
    server.use(http.post('/api/bff/platform/tenants/:id/activation', () => HttpResponse.json({ code: 'business-rule' }, { status: 409 })));
    const user = await open(VIEW_DETAIL_READY, CONSENTED);
    await user.click(await within(step('Go live')).findByRole('button', { name: 'Go live' }));
    await user.click(await screen.findByRole('button', { name: 'Yes, go live' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('It cannot go live yet. The page has been read again.');
  });

  it('can be cancelled out of', async () => {
    const user = await open(VIEW_DETAIL_READY, CONSENTED);
    await user.click(await within(step('Go live')).findByRole('button', { name: 'Go live' }));
    await user.click(await screen.findByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(seenOperatorWrites).toEqual([]);
  });

  it('opens a live organisation on Go live, says it is live, and has no Go live button', async () => {
    await open(VIEW_DETAIL_ACTIVE);
    expect(screen.getByRole('heading', { level: 2, name: 'Go live' })).toBeInTheDocument();
    expect(within(step('Go live')).getByText(/This organisation is live since 22 Oct 2026/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Go live' })).not.toBeInTheDocument();
  });

  it('shows a live organisation in a banner that says who can now sign in', async () => {
    await open(VIEW_DETAIL_ACTIVE);
    const banner = within(step('Go live')).getByRole('status');
    expect(banner).toHaveTextContent(/This organisation is live since 22 Oct 2026/);
    expect(banner).toHaveTextContent('Staff of every role can sign in at their address.');
  });

  it('explains when Go live opens, and shows each task of their administrators as a To do tag with its words', async () => {
    await open({ ...VIEW_DETAIL_PROVISIONING, activation: { ready: false, blockers: ['Retention set for every data class', 'Area districts set'] } }, undefined, 'Go live');
    const card = step('Go live');
    expect(within(card).getByText('Their administrators finish these after they sign in. Go live is available when every one is done and the four parts before it are finished.')).toBeInTheDocument();
    const theirs = await within(card).findByRole('list', { name: 'Their administrators finish these' });
    const tags =theirs.querySelectorAll('[data-variant="todo"]');
    expect(tags).toHaveLength(within(theirs).getAllByRole('listitem').length);
    expect(tags.length).toBeGreaterThan(0);
    expect(tags[0]).toHaveTextContent('To do');
  });

  it('has no axe violations when ready', async () => {
    await open(VIEW_DETAIL_READY, CONSENTED);
    await within(step('Go live')).findByRole('button', { name: 'Go live' });
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});
