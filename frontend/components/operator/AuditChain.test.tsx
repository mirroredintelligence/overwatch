import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { server } from '@/test/msw/server';
import { AuditChain } from './AuditChain';

// The platform audit chain (TEN-083, DEC-1002): what the platform's own people did, oldest first, a page at
// a time, and a check that the whole chain is intact. An unreadable or broken chain is said plainly.

describe('AuditChain', () => {
  it('lists the first page oldest first, with the step in words, who did it and which tenant', async () => {
    render(<AuditChain />);
    const table = await screen.findByRole('table', { name: 'The platform audit chain' });
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['No.', 'When', 'What happened', 'Account', 'Tenant']);
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(3);
    expect(within(rows[0]!).getByText('Signed in')).toBeInTheDocument();
    expect(within(rows[0]!).getByText('ops-0123456789abcdef0123456789abcdef')).toBeInTheDocument();
    expect(within(rows[1]!).getByText('Tenant created')).toBeInTheDocument();
    expect(within(rows[1]!).getByText('trust-b')).toBeInTheDocument();
    expect(within(rows[2]!).getByText('Support access requested')).toBeInTheDocument();
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
    await user.click(await screen.findByRole('button', { name: 'Load more' }));
    await screen.findByText('Tenant activated');
    expect(asked).toEqual(['0', '1']);
    expect(screen.getAllByRole('row')).toHaveLength(3);
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
  });

  it('shows a step it has no words for as the back end names it', async () => {
    server.use(http.get('/api/bff/platform/audit', () => HttpResponse.json({ entries: [{ seq: 9, action: 'something-new', principalRef: 'ops-1', tenantId: null, accessId: null, snapshot: null, at: '2026-10-20T09:00:00Z' }], next: null })));
    render(<AuditChain />);
    expect(await screen.findByText('something-new')).toBeInTheDocument();
  });

  it('says the chain is intact when it is', async () => {
    const user = userEvent.setup();
    render(<AuditChain />);
    await user.click(await screen.findByRole('button', { name: 'Check the chain' }));
    expect(await screen.findByRole('status')).toHaveTextContent('The chain is intact.');
  });

  it('says plainly, as an alert, that the chain is NOT intact when it is not', async () => {
    server.use(http.get('/api/bff/platform/audit/verification', () => HttpResponse.json({ intact: false })));
    const user = userEvent.setup();
    render(<AuditChain />);
    await user.click(await screen.findByRole('button', { name: 'Check the chain' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The chain is not intact. Do not rely on it. Tell the person who looks after the platform record now.');
  });

  it('says the check could not be made, and does not say it is intact, when it fails', async () => {
    server.use(http.get('/api/bff/platform/audit/verification', () => HttpResponse.json({}, { status: 503 })));
    const user = userEvent.setup();
    render(<AuditChain />);
    await user.click(await screen.findByRole('button', { name: 'Check the chain' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The check could not be made. Try again.');
    expect(screen.queryByText('The chain is intact.')).not.toBeInTheDocument();
  });

  it('says it could not load the chain, never an empty one', async () => {
    server.use(http.get('/api/bff/platform/audit', () => HttpResponse.json({}, { status: 503 })));
    render(<AuditChain />);
    expect(await screen.findByRole('alert')).toHaveTextContent('We could not load the audit chain.');
    await waitFor(() => expect(screen.queryByRole('table')).not.toBeInTheDocument());
  });

  it('has no axe violations', async () => {
    render(<AuditChain />);
    await screen.findByRole('table');
    expect(await runAxe(document.body)).toHaveNoViolations();
  });
});
