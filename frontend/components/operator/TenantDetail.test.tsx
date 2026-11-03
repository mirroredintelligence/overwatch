import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { CONSENTED, VIEW_DETAIL_PROVISIONING, VIEW_DETAIL_READY } from '@/test/fixtures/operator';
import { resetOperatorWrites } from '@/test/msw/handlers/operator';
import { server } from '@/test/msw/server';
import { TenantDetail } from './TenantDetail';

// One partner organisation's page (TEN-083) as a guided "Go live": a task list of five parts (each a link with its
// status in words and one line on where it stands) and only the selected part beside it, by default the first that is
// not completed. A completed part shows a short summary and a Change link. Its identifiers are under a closed
// "Technical details" disclosure; Go live only when everything is done. Every write is the operator's own, with its
// CSRF token and one idempotency key per submit, and is the same write as before. A step that was done and not
// recorded by the platform chain is said so, and is never offered again. No secret is ever shown.
//
// This file keeps what the page shows as a whole. Each step's own behaviour is tested next to the step, in
// ./funnel/<Step>.test.tsx (Go live, sign-in, invite, team, roles, reach, agreements, and the suspend/close panel).

beforeEach(() => resetOperatorWrites());

type Detail = typeof VIEW_DETAIL_READY;
const serveConsent = (body: unknown) => server.use(http.get('/api/bff/platform/tenants/:id/admin-consent', () => HttpResponse.json(body as Record<string, unknown>)));
function serve(detail: unknown) {
  server.use(http.get('/api/bff/platform/tenants/:id', () => HttpResponse.json(detail as Record<string, unknown>)));
}
const PHASES = ['Organisation and sign-in', 'Administrator approval', 'Teams and people', 'Reach and agreements', 'Go live'];
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
/** The steps shown now. */
const shownSteps = () => Array.from(document.querySelectorAll('[data-el^="OP-STEP-"]')) as HTMLElement[];
/** An element's text with its closed disclosures taken out. */
const bare = (el: HTMLElement) => {
  const clone = el.cloneNode(true) as HTMLElement;
  clone.querySelectorAll('details').forEach((d) => d.remove());
  return clone.textContent ?? '';
};
const step = (name: string) => screen.getByRole('region', { name });
/** What a step shows with its closed technical details taken out. */
const headline = (name: string): string => bare(step(name));
const detailsOf = (name: string) => within(Array.from(step(name).querySelectorAll('details')).find((d) => d.querySelector('summary')?.textContent === 'Technical details') as HTMLElement);
const ready = (over: Partial<Detail> = {}): Detail => ({ ...VIEW_DETAIL_READY, ...over });

describe('what the page shows', () => {
  it('has one h1 with the organisation’s name, its status in words, and one h2: the selected part', async () => {
    await open();
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    expect(screen.getByText('Being set up')).toBeInTheDocument();
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual(['Organisation and sign-in']);
    expect(screen.getByText('0 of 5 parts completed')).toBeInTheDocument();
  });

  it('shows the five parts as a task list, each a link with its status in words and a line on where it stands', async () => {
    await open();
    const nav = screen.getByRole('navigation', { name: 'Go live tasks' });
    const items = within(nav).getAllByRole('listitem');
    expect(items).toHaveLength(5);
    items.forEach((li, i) => expect(within(li).getByRole('link').textContent?.replace(/^\d/, '').startsWith(PHASES[i]!)).toBe(true));
    expect(items[0]).toHaveTextContent('In progress');
    expect(items[0]).toHaveTextContent('A Microsoft work account is waiting for you to confirm it.');
    expect(items[1]).toHaveTextContent('Not started');
    expect(items[1]).toHaveTextContent('Connect their Microsoft work accounts first.');
    expect(items[4]).toHaveTextContent('Not started');
  });

  it('marks the selected part with aria-current, opens on the first that is not completed, and moves with the choice', async () => {
    const user = await open(ready({ bindings: VIEW_DETAIL_PROVISIONING.bindings.map((b) => ({ ...b, status: 'verified' as const })) }));
    const nav = screen.getByRole('navigation', { name: 'Go live tasks' });
    const link = (name: string) => within(nav).getByRole('link', { name: new RegExp(`^${name}`) });
    expect(link('Administrator approval')).toHaveAttribute('aria-current', 'step');
    expect(link('Organisation and sign-in')).not.toHaveAttribute('aria-current');
    expect(link('Organisation and sign-in')).toHaveTextContent('Completed');
    expect(screen.getByRole('heading', { level: 2, name: 'Administrator approval' })).toBeInTheDocument();
    await user.click(link('Reach and agreements'));
    expect(link('Reach and agreements')).toHaveAttribute('aria-current', 'step');
    expect(link('Administrator approval')).not.toHaveAttribute('aria-current');
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual(['Reach and agreements']);
  });

  it('moves focus to the heading of the part that was chosen', async () => {
    const user = await open();
    await choose(user, 'Teams and people');
    expect(screen.getByRole('heading', { level: 2, name: 'Teams and people' })).toHaveFocus();
  });

  it('has at most one primary button in the selected part, and it is the next thing to do', async () => {
    const user = await open();
    const primaries = () => Array.from(document.querySelectorAll('button[data-variant="primary"]')).map((b) => b.textContent);
    expect(primaries()).toEqual(['Confirm this is their Microsoft account']);
    for (const phase of ['Teams and people', 'Reach and agreements', 'Go live']) {
      await choose(user, phase);
      expect(primaries().length).toBeLessThanOrEqual(1);
    }
    await choose(user, 'Reach and agreements');
    expect(primaries()).toEqual(['Save web address']);
  });

  it('keeps fields to a readable width, in a form of their own', async () => {
    await open(VIEW_DETAIL_PROVISIONING, undefined, 'Reach and agreements');
    const form = screen.getByRole('form', { name: 'Set the web address' });
    expect(form.className).toMatch(/form/);
  });

  it('has no axe violations in any part', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, CONSENTED);
    for (const phase of PHASES) {
      await choose(user, phase);
      expect(await runAxe(document.body)).toHaveNoViolations();
    }
  });

  it('says a part is waiting for them while the approval link is out', async () => {
    await open(ready({ bindings: VIEW_DETAIL_PROVISIONING.bindings.map((b) => ({ ...b, status: 'verified' as const })) }), { invitation: { emailMasked: 'j***@example-trust.test', status: 'pending', createdAt: '2026-11-01T09:00:00Z', expiresAt: '2026-11-08T09:00:00Z', consentedAt: null, reason: null } });
    const nav = screen.getByRole('navigation', { name: 'Go live tasks' });
    const item = within(nav).getByRole('link', { name: /^Administrator approval/ }).closest('li') as HTMLElement;
    await waitFor(() => expect(item).toHaveTextContent('Waiting for them'));
    expect(item).toHaveTextContent('Approval link sent. Waiting for their administrator.');
  });

  it('shows a completed part as a short summary with a Change link, and the steps only once Change is chosen', async () => {
    const user = await open(VIEW_DETAIL_READY, CONSENTED);
    await choose(user, 'Teams and people');
    const change = await screen.findByRole('button', { name: /^Change/ });
    const panel = screen.getByRole('region', { name: 'Teams and people' });
    expect(within(panel).getByText('Administrators’ team')).toBeInTheDocument();
    expect(within(panel).getByText('Shift leads')).toBeInTheDocument();
    expect(within(panel).queryByRole('checkbox')).not.toBeInTheDocument();
    expect(within(panel).queryByRole('button', { name: 'Add to team' })).not.toBeInTheDocument();
    await user.click(change);
    expect(await within(panel).findByRole('button', { name: 'Add to team' })).toBeInTheDocument();
  });

  it('confirms the organisation with the NHS code and plain words, and keeps the identifiers under technical details', async () => {
    await open();
    const text = headline('Check the organisation');
    expect(text).toContain('NHS code');
    expect(text).toContain('RYY02');
    expect(text).toContain('Sample Area B Organisation');
    expect(text).toContain('Integrated care board');
    expect(text).toContain('United Kingdom');
    expect(text).toContain('Europe/London');
    expect(text).not.toMatch(/ODS|trust-b/);
    expect(detailsOf('Check the organisation').getByText('trust-b')).toBeInTheDocument();
    expect(detailsOf('Check the organisation').getByText('ODS code')).toBeInTheDocument();
  });

  it('has the technical details as a real disclosure that is closed by default', async () => {
    await open();
    const summary = within(step('Check the organisation')).getByText('Technical details');
    expect(summary.tagName).toBe('SUMMARY');
    expect(summary.closest('details')).not.toHaveAttribute('open');
    expect(screen.queryByText('Details', { exact: true })).not.toBeInTheDocument();
  });

  it('holds every technical identifier under technical details and none on the face of a part, whichever part is chosen', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, CONSENTED);
    const ids = ['11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222', 'trust-b', 'ACsampleaccount00000000000000000001'];
    for (const phase of PHASES) {
      await choose(user, phase);
      for (const el of shownSteps()) {
        for (const id of ids) expect(bare(el)).not.toContain(id);
        expect(el.querySelector('details[open]')).toBeNull();
      }
    }
    await choose(user, 'Organisation and sign-in');
    expect(detailsOf('Connect their Microsoft work accounts').getByText('11111111-1111-4111-8111-111111111111')).toBeInTheDocument();
    await choose(user, 'Teams and people');
    expect(detailsOf('Other teams').getByText('22222222-2222-4222-8222-222222222222')).toBeInTheDocument();
    await choose(user, 'Reach and agreements');
    expect(detailsOf('Web address and text number').getByText('ACsampleaccount00000000000000000001')).toBeInTheDocument();
    expect(step('Agreements (recommended)').querySelector('details')).toBeNull();
  });

  it('uses no jargon on the face of any part or of the task list', async () => {
    const user = await open(VIEW_DETAIL_PROVISIONING, CONSENTED);
    const jargon = /\b(directory|Entra|tenant|group object|role mapping|ODS)\b/i;
    for (const phase of PHASES) {
      await choose(user, phase);
      expect(bare(screen.getByRole('region', { name: phase }))).not.toMatch(jargon);
    }
    expect(bare(screen.getByRole('navigation', { name: 'Go live tasks' }))).not.toMatch(jargon);
  });

  it('shows a number with its state and whether it has been tested, and never a secret', async () => {
    await open(VIEW_DETAIL_PROVISIONING, undefined, 'Reach and agreements');
    const list = within(step('Web address and text number')).getByRole('list', { name: 'Text numbers' });
    const row = within(list).getByRole('listitem');
    expect(row).toHaveTextContent('+441632960002 · In use · Not tested');
    expect(document.body.textContent ?? '').not.toMatch(/authTokenRef|tenants\/trust-b|Auth token/);
  });

  it('shows the agreements held', async () => {
    await open(VIEW_DETAIL_PROVISIONING, undefined, 'Reach and agreements');
    const refs = step('Agreements (recommended)');
    expect(within(refs).getByText('DSA-2026-014')).toBeInTheDocument();
    expect(within(refs).getByText(/recommended/, { selector: 'p' })).toBeInTheDocument();
    expect(within(refs).getByText('Clinical safety case', { selector: 'dt' })).toBeInTheDocument();
    expect(within(refs).getAllByText('Not recorded')).toHaveLength(2);
  });

  it('says it could not find the organisation on a 404, and could not load it on another failure', async () => {
    server.use(http.get('/api/bff/platform/tenants/:id', () => HttpResponse.json({ code: 'not-found' }, { status: 404 })));
    const { unmount } = render(<TenantDetail tenantId="trust-x" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not find that organisation.');
    unmount();
    server.use(http.get('/api/bff/platform/tenants/:id', () => HttpResponse.json({}, { status: 503 })));
    render(<TenantDetail tenantId="trust-x" />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load the organisation.');
  });

  it('has no axe violations', async () => {
    await open();
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});
