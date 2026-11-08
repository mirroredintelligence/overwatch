import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import {
  CONSENTED,
  VIEW_DETAIL_ACTIVE,
  VIEW_DETAIL_PROVISIONING,
  VIEW_DETAIL_READY,
  VIEW_DETAIL_SUSPENDED,
  VIEW_TENANTS_SUPPORT,
} from '@/test/fixtures/operator';
import { server } from '@/test/msw/server';
import { TenantList } from './TenantList';

// The console's first page (TEN-083, board O2): the organisations. The operator sees one card per organisation
// with its type, its ODS code and address, its status in words, and how far its go-live has got (five parts, a
// bar and the next step in words). Cards are filtered by status and by name or address. A support person sees
// the name and the status and can ask to look into an active one. Neither sees a person.

afterEach(() => vi.unstubAllGlobals());

/** The three sample organisations of the list, each with its own detail and approval link. */
function serve(details: Record<string, unknown>, consents: Record<string, unknown> = {}) {
  server.use(
    http.get('/api/bff/platform/tenants/:id', ({ params }) => HttpResponse.json(details[String(params.id)] ?? {}, { status: details[String(params.id)] ? 200 : 404 })),
    http.get('/api/bff/platform/tenants/:id/admin-consent', ({ params }) => HttpResponse.json(consents[String(params.id)] ?? { invitation: null })),
  );
}
const ALL_ACTIVE = { 'trust-a': VIEW_DETAIL_ACTIVE, 'trust-b': VIEW_DETAIL_PROVISIONING, 'trust-c': VIEW_DETAIL_SUSPENDED };
const PENDING = { invitation: { ...CONSENTED.invitation, status: 'pending', consentedAt: null } };

/** The card of one organisation, found by its name. */
// The item is taken from the list, not from its heading: the heading is re-rendered when the card's detail arrives.
async function card(name: string): Promise<HTMLElement> {
  const list = await screen.findByRole('list', { name: 'Organisations' });
  const found = within(list)
    .getAllByRole('listitem')
    .find((item) => item.querySelector('h2')?.textContent === name);
  if (found === undefined) throw new Error(`No card named ${name}`);
  return found;
}

describe('TenantList for the platform operator', () => {
  it('shows one card per organisation, with its type, its ODS code, its address and its status in words', async () => {
    serve(ALL_ACTIVE);
    render(<TenantList role="platform-operator" />);
    const list = await screen.findByRole('list', { name: 'Organisations' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(3);
    const a = await card('Sample Area A');
    expect(await within(a).findByText('NHS trust · RYY02 · tenant-a.example.test')).toBeInTheDocument();
    expect(within(a).getByText('Live')).toBeInTheDocument();
    const b = await card('Sample Area B');
    expect(within(b).getByText('Being set up')).toBeInTheDocument();
    expect(within(b).getByText('Integrated care board · RYY02')).toBeInTheDocument();
    const c = await card('Sample Area C');
    expect(within(c).getByText('Suspended')).toBeInTheDocument();
  });

  it('shows a set-up organisation’s progress as five parts, a bar and the next step in words', async () => {
    serve({ 'trust-a': VIEW_DETAIL_ACTIVE, 'trust-b': VIEW_DETAIL_READY, 'trust-c': VIEW_DETAIL_SUSPENDED }, { 'trust-b': CONSENTED });
    render(<TenantList role="platform-operator" />);
    const b = await card('Sample Area B');
    expect(await within(b).findByRole('img', { name: '4 of 5 parts done' })).toBeInTheDocument();
    expect(within(b).getByText(/4 of 5 parts/)).toBeInTheDocument();
    expect(within(b).getByText('Ready to go live')).toBeInTheDocument();
  });

  it('says what a set-up organisation is waiting for, in words, when its administrator has not approved yet', async () => {
    const verified = { ...VIEW_DETAIL_PROVISIONING, bindings: [{ directoryId: '11111111-1111-4111-8111-111111111111', status: 'verified', verifiedAt: '2026-10-21T09:00:00Z' }] };
    serve({ 'trust-a': VIEW_DETAIL_ACTIVE, 'trust-b': verified, 'trust-c': VIEW_DETAIL_SUSPENDED }, { 'trust-b': PENDING });
    render(<TenantList role="platform-operator" />);
    const b = await card('Sample Area B');
    expect(await within(b).findByRole('img', { name: '1 of 5 parts done' })).toBeInTheDocument();
    expect(within(b).getByText('Waiting for their administrator')).toBeInTheDocument();
  });

  it('says when a live organisation went live', async () => {
    serve(ALL_ACTIVE);
    render(<TenantList role="platform-operator" />);
    const a = await card('Sample Area A');
    expect(await within(a).findByText(/Live since 1 Oct/)).toBeInTheDocument();
    expect(within(a).queryByRole('img', { name: /parts done/ })).not.toBeInTheDocument();
  });

  it('keeps what a card already shows in place when its detail arrives, instead of putting it up again', async () => {
    serve(ALL_ACTIVE);
    // The line is taken the moment it first appears: a test that looks for it later can only find the second copy.
    let first: HTMLElement | null = null;
    const watch = new MutationObserver(() => {
      first ??= Array.from(document.querySelectorAll<HTMLElement>('p')).find((p) => /Live since 1 Oct/.test(p.textContent ?? '')) ?? null;
    });
    watch.observe(document.body, { childList: true, subtree: true });
    render(<TenantList role="platform-operator" />);
    // The card becomes "seen" in the next tick and then reads its detail (the ODS code comes with it).
    await within(await card('Sample Area A')).findByText(/RYY02/);
    watch.disconnect();
    // The line seen first is still on the card, not one put up again in its place.
    expect(first).not.toBeNull();
    expect((first as unknown as HTMLElement).isConnected).toBe(true);
  });

  it('links each card’s Open button to the organisation’s page, named by its organisation', async () => {
    serve(ALL_ACTIVE);
    render(<TenantList role="platform-operator" />);
    expect(await screen.findByRole('link', { name: 'Open Sample Area B' })).toHaveAttribute('href', '/operator/tenants/trust-b');
    expect(screen.getByRole('link', { name: 'Open Sample Area A' })).toHaveAttribute('href', '/operator/tenants/trust-a');
  });

  it('shows the status chips with how many organisations each holds, and filters by them', async () => {
    serve(ALL_ACTIVE);
    render(<TenantList role="platform-operator" />);
    await screen.findByRole('list', { name: 'Organisations' });
    expect(screen.getByRole('button', { name: 'All · 3' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Being set up · 1' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('button', { name: 'Live · 1' })).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(screen.getByRole('button', { name: 'Live · 1' }));
    expect(screen.getByRole('button', { name: 'Live · 1' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getAllByRole('listitem')).toHaveLength(1);
    expect(screen.getByRole('heading', { name: 'Sample Area A' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Being set up · 1' }));
    expect(screen.getAllByRole('listitem')).toHaveLength(1);
    expect(screen.getByRole('heading', { name: 'Sample Area B' })).toBeInTheDocument();
  });

  it('finds an organisation by its name or its address, and says when none matches', async () => {
    serve(ALL_ACTIVE);
    render(<TenantList role="platform-operator" />);
    await screen.findByRole('list', { name: 'Organisations' });
    const search = screen.getByRole('searchbox', { name: 'Find an organisation' });
    fireEvent.change(search, { target: { value: 'tenant-c' } });
    expect(screen.getAllByRole('listitem')).toHaveLength(1);
    expect(screen.getByRole('heading', { name: 'Sample Area C' })).toBeInTheDocument();
    fireEvent.change(search, { target: { value: 'nothing like this' } });
    expect(screen.queryAllByRole('listitem')).toHaveLength(0);
    expect(screen.getByRole('status')).toHaveTextContent('No organisation matches.');
  });

  it('offers creating an organisation once, beside the heading, and never a second action', async () => {
    serve(ALL_ACTIVE);
    render(<TenantList role="platform-operator" />);
    await screen.findByRole('list', { name: 'Organisations' });
    expect(screen.getAllByRole('link', { name: 'Create an organisation' })).toHaveLength(1);
    expect(screen.getByRole('link', { name: 'Create an organisation' })).toHaveAttribute('href', '/operator/tenants/new');
  });

  it('says there are none, with the next step, and says it could not load, in the right cases', async () => {
    server.use(http.get('/api/bff/platform/tenants', () => HttpResponse.json({ tenants: [] })));
    const { unmount } = render(<TenantList role="platform-operator" />);
    expect(await screen.findByRole('heading', { name: 'There are no organisations yet.' })).toBeInTheDocument();
    unmount();
    server.use(http.get('/api/bff/platform/tenants', () => HttpResponse.json({}, { status: 503 })));
    render(<TenantList role="platform-operator" />);
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('We could not load the organisations.');
    expect(within(alert).getByRole('button', { name: 'Try again' })).toBeInTheDocument();
    expect(screen.queryByText('There are no organisations yet.')).not.toBeInTheDocument();
  });

  it('turns an empty list into a next step, with what comes after the first organisation', async () => {
    server.use(http.get('/api/bff/platform/tenants', () => HttpResponse.json({ tenants: [] })));
    const { container } = render(<TenantList role="platform-operator" />);
    const empty = await screen.findByRole('region', { name: 'There are no organisations yet.' });
    expect(within(empty).getByText(/give it an address, bind its directory/)).toBeInTheDocument();
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows a loading state that says what it is loading', () => {
    server.use(http.get('/api/bff/platform/tenants', () => new Promise(() => {})));
    render(<TenantList role="platform-operator" />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading the organisations.');
  });

  it('reads an organisation’s progress only once its card is in view', async () => {
    const observers: { callback: IntersectionObserverCallback; target: Element }[] = [];
    class FakeObserver {
      constructor(private readonly callback: IntersectionObserverCallback) {}
      observe(target: Element) {
        observers.push({ callback: this.callback, target });
      }
      unobserve() {}
      disconnect() {}
      takeRecords() {
        return [];
      }
    }
    vi.stubGlobal('IntersectionObserver', FakeObserver);
    serve({ 'trust-a': VIEW_DETAIL_ACTIVE, 'trust-b': VIEW_DETAIL_READY, 'trust-c': VIEW_DETAIL_SUSPENDED }, { 'trust-b': CONSENTED });
    render(<TenantList role="platform-operator" />);
    const cardB = await card('Sample Area B');
    expect(within(cardB).queryByRole('img', { name: /parts done/ })).not.toBeInTheDocument();
    const watch = observers.find((o) => o.target === cardB);
    expect(watch).toBeDefined();
    act(() => watch!.callback([{ isIntersecting: true, target: cardB } as unknown as IntersectionObserverEntry], {} as IntersectionObserver));
    expect(await within(cardB).findByRole('img', { name: '4 of 5 parts done' })).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    serve(ALL_ACTIVE);
    render(<TenantList role="platform-operator" />);
    await screen.findByRole('list', { name: 'Organisations' });
    await screen.findByRole('img', { name: '0 of 5 parts done' });
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});

describe('TenantList for a support person', () => {
  it('has an empty state with no button to create one: a support person asks a platform operator', async () => {
    server.use(http.get('/api/bff/platform/tenants', () => HttpResponse.json({ tenants: [] })));
    render(<TenantList role="support" />);
    const empty = await screen.findByRole('region', { name: 'There are no organisations yet.' });
    expect(within(empty).queryByRole('link')).not.toBeInTheDocument();
    expect(within(empty).getByText(/When a platform operator creates one/)).toBeInTheDocument();
  });

  it('shows the name and the status only, with no link to an organisation’s page and no way to create one', async () => {
    server.use(http.get('/api/bff/platform/tenants', () => HttpResponse.json(VIEW_TENANTS_SUPPORT)));
    render(<TenantList role="support" />);
    const table = await screen.findByRole('table', { name: 'Organisations' });
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Name', 'Status', 'Ask to look in']);
    expect(screen.queryByRole('link', { name: 'Sample Area A' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Create an organisation' })).not.toBeInTheDocument();
    expect(document.body.textContent ?? '').not.toMatch(/example\.test|NHS trust/);
  });

  it('offers to ask for access to an active organisation only', async () => {
    server.use(http.get('/api/bff/platform/tenants', () => HttpResponse.json(VIEW_TENANTS_SUPPORT)));
    render(<TenantList role="support" />);
    await screen.findByRole('table');
    const links = screen.getAllByRole('link');
    expect(links.map((a) => [a.textContent, a.getAttribute('href')])).toEqual([['Ask for access to Sample Area A', '/operator/support/new?for=trust-a']]);
  });
});
