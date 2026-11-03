import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { AuditChain } from './AuditChain';

// The platform audit chain (TEN-083, DEC-1002): what the platform's own people did, oldest first, a page at
// a time, and a check that the whole chain is intact. An unreadable or broken chain is said plainly, and a
// broken chain hides nothing.

function timelineItems() {
  return within(screen.getByRole('list', { name: 'Entries' })).getAllByRole('listitem');
}

describe('AuditChain', () => {
  it('shows the chain as a timeline, oldest first, with the step in words, the account and the tenant', async () => {
    render(<AuditChain />);
    const list = await screen.findByRole('list', { name: 'Entries' });
    const rows = within(list).getAllByRole('listitem');
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent('Signed in');
    expect(rows[0]).toHaveTextContent('ops-0123456789abcdef0123456789abcdef');
    expect(rows[1]).toHaveTextContent('Tenant created');
    expect(rows[1]).toHaveTextContent('trust-b');
    expect(rows[2]).toHaveTextContent('Support access requested');
  });

  it('says what the chain is for, in the words of the board', async () => {
    render(<AuditChain />);
    expect(await screen.findByText('What the platform’s own people did. Each entry is linked to the one before it, so a change to the past shows.')).toBeInTheDocument();
  });

  it('filters the entries to one group, and says which group is showing', async () => {
    const user = userEvent.setup();
    render(<AuditChain />);
    await screen.findByRole('list', { name: 'Entries' });
    await user.click(screen.getByRole('button', { name: 'Sign-ins' }));
    expect(screen.getByRole('button', { name: 'Sign-ins' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Everything' })).toHaveAttribute('aria-pressed', 'false');
    expect(timelineItems()).toHaveLength(1);
    expect(timelineItems()[0]).toHaveTextContent('Signed in');
    await user.click(screen.getByRole('button', { name: 'Organisations' }));
    expect(timelineItems()).toHaveLength(1);
    expect(timelineItems()[0]).toHaveTextContent('Tenant created');
    await user.click(screen.getByRole('button', { name: 'Everything' }));
    expect(timelineItems()).toHaveLength(3);
  });

  it('says so, and does not show an empty chain, when a group has nothing in it', async () => {
    server.use(
      http.get('/api/bff/platform/audit', () =>
        HttpResponse.json({ entries: [{ seq: 1, action: 'operator-signed-in', principalRef: 'ops-1', tenantId: null, accessId: null, snapshot: null, at: '2026-10-20T09:00:00Z' }], next: null }),
      ),
    );
    const user = userEvent.setup();
    render(<AuditChain />);
    await screen.findByRole('list', { name: 'Entries' });
    await user.click(screen.getByRole('button', { name: 'Support access' }));
    expect(screen.getByText('Nothing in this group yet.')).toBeInTheDocument();
    expect(screen.queryByRole('list', { name: 'Entries' })).not.toBeInTheDocument();
  });

  it('lets the filter buttons be used from the keyboard', async () => {
    const user = userEvent.setup();
    render(<AuditChain />);
    await screen.findByRole('list', { name: 'Entries' });
    screen.getByRole('button', { name: 'Organisations' }).focus();
    await user.keyboard('{Enter}');
    expect(screen.getByRole('button', { name: 'Organisations' })).toHaveAttribute('aria-pressed', 'true');
    expect(timelineItems()).toHaveLength(1);
  });

  it('says nothing has been recorded yet when the chain is empty', async () => {
    server.use(http.get('/api/bff/platform/audit', () => HttpResponse.json({ entries: [], next: null })));
    render(<AuditChain />);
    expect(await screen.findByText('Nothing has been recorded yet.')).toBeInTheDocument();
    expect(screen.queryByRole('list', { name: 'Entries' })).not.toBeInTheDocument();
  });

  it('announces the loading as a busy status, with the page’s words for it', () => {
    render(<AuditChain />);
    const status = screen.getByRole('status');
    expect(status).toHaveAttribute('aria-busy', 'true');
    expect(status).toHaveTextContent('Loading the audit chain.');
  });

  it('loads the next page after the last number seen, and stops offering when there is no more', async () => {
    const asked: string[] = [];
    server.use(
      http.get('/api/bff/platform/audit', ({ request }) => {
        const after = new URL(request.url).searchParams.get('afterSeq') ?? '';
        asked.push(after);
        return HttpResponse.json(after === '0' ? { entries: [{ seq: 1, action: 'tenant-created', principalRef: 'ops-1', tenantId: 'trust-b', accessId: null, snapshot: null, at: '2026-10-20T09:00:00Z' }], next: 1 } : { entries: [{ seq: 2, action: 'tenant-activated', principalRef: 'ops-1', tenantId: 'trust-b', accessId: null, snapshot: null, at: '2026-10-22T09:00:00Z' }], next: null });
      }),
    );
    const user = userEvent.setup();
    render(<AuditChain />);
    await user.click(await screen.findByRole('button', { name: 'Show later entries' }));
    await screen.findByText('Tenant activated');
    expect(asked).toEqual(['0', '1']);
    expect(timelineItems()).toHaveLength(2);
    expect(screen.queryByRole('button', { name: 'Show later entries' })).not.toBeInTheDocument();
  });

  it('shows a step it has no words for as the back end names it', async () => {
    server.use(http.get('/api/bff/platform/audit', () => HttpResponse.json({ entries: [{ seq: 9, action: 'something-new', principalRef: 'ops-1', tenantId: null, accessId: null, snapshot: null, at: '2026-10-20T09:00:00Z' }], next: null })));
    render(<AuditChain />);
    expect(await screen.findByText('something-new')).toBeInTheDocument();
  });

  it('says the chain has not been checked yet, and does not say it is intact, before a check', async () => {
    render(<AuditChain />);
    await screen.findByRole('list', { name: 'Entries' });
    expect(screen.getByText('The chain has not been checked yet. Check it to see whether every entry still matches the one before it.')).toBeInTheDocument();
    expect(screen.queryByText('The chain is intact.')).not.toBeInTheDocument();
  });

  it('says the chain is intact when it is, and then offers to check it again', async () => {
    const user = userEvent.setup();
    render(<AuditChain />);
    await user.click(await screen.findByRole('button', { name: 'Check the chain' }));
    expect(await screen.findByRole('status')).toHaveTextContent('The chain is intact.');
    expect(screen.getByRole('button', { name: 'Check it again' })).toBeInTheDocument();
  });

  it('says plainly, as an alert, that the chain is NOT intact when it is not, and hides no entry', async () => {
    server.use(http.get('/api/bff/platform/audit/verification', () => HttpResponse.json({ intact: false })));
    const user = userEvent.setup();
    render(<AuditChain />);
    await user.click(await screen.findByRole('button', { name: 'Check the chain' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The chain is not intact. Do not rely on it. Tell the person who looks after the platform record now.');
    expect(timelineItems()).toHaveLength(3);
  });

  it('says the check could not be made, does not say it is intact, and offers to try again', async () => {
    server.use(http.get('/api/bff/platform/audit/verification', () => HttpResponse.json({}, { status: 503 })));
    const user = userEvent.setup();
    render(<AuditChain />);
    await user.click(await screen.findByRole('button', { name: 'Check the chain' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The check could not be made. Try again.');
    expect(screen.queryByText('The chain is intact.')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Check it again' })).toBeInTheDocument();
  });

  it('says it could not load the chain, never an empty one', async () => {
    server.use(http.get('/api/bff/platform/audit', () => HttpResponse.json({}, { status: 503 })));
    render(<AuditChain />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load the audit chain.');
    await waitFor(() => expect(screen.queryByRole('list', { name: 'Entries' })).not.toBeInTheDocument());
  });

  it('has no axe violations', async () => {
    render(<AuditChain />);
    await screen.findByRole('list', { name: 'Entries' });
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});
