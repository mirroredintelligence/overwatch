import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { resetLeadPosts, seenLeadPosts } from '@/test/msw/handlers/lead';
import { server } from '@/test/msw/server';
import { SetupTracker } from './SetupTracker';

// Track set-up (W43; INV-01): the list of invitations and, beside it, one reporter's set-up. The open reporter is
// in the address, /lead/reporters?invitation=<id>, so Back and a reload work. The list never goes away.

// The page's address is a small store the mock of next/navigation reads and writes.
const nav = vi.hoisted(() => {
  const listeners = new Set<() => void>();
  const state = { search: '', pushed: [] as string[] };
  return {
    state,
    subscribe: (l: () => void) => {
      listeners.add(l);
      return () => void listeners.delete(l);
    },
    set(search: string) {
      state.search = search;
      state.pushed = [];
    },
    push(url: string) {
      state.pushed.push(url);
      state.search = url.includes('?') ? url.slice(url.indexOf('?') + 1) : '';
      listeners.forEach((l) => l());
    },
  };
});

vi.mock('next/navigation', async () => {
  const { useSyncExternalStore } = await import('react');
  const search = () => nav.state.search;
  return {
    useSearchParams: () => new URLSearchParams(useSyncExternalStore(nav.subscribe, search, search)),
    useRouter: () => ({ push: nav.push, replace: nav.push, back: () => nav.push('/lead/reporters') }),
    usePathname: () => '/lead/reporters',
  };
});

beforeEach(() => {
  resetLeadPosts();
  nav.set('');
  document.cookie = 'overwatch_csrf=test-csrf-token';
});

function detail(name: string): HTMLElement {
  return screen.getByRole('region', { name });
}

describe('SetupTracker', () => {
  it('has the page heading Reporters and the list of invitations with the heading Set-up progress', async () => {
    render(<SetupTracker />);
    expect(screen.getByRole('heading', { level: 1, name: 'Reporters' })).toBeInTheDocument();
    const list = await screen.findByRole('list');
    expect(screen.getByRole('heading', { level: 2, name: 'Set-up progress' })).toBeInTheDocument();
    const rows = within(list).getAllByRole('button');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('UCR West');
    expect(rows[0]).toHaveTextContent('Stuck');
    expect(rows[0]).toHaveTextContent('Waiting at: Notifications on');
    expect(rows[1]).toHaveTextContent('Reablement');
    expect(rows[1]).toHaveTextContent('Complete');
  });

  it('shows a shimmer that says it is loading, until the list arrives', async () => {
    render(<SetupTracker />);
    expect(screen.getByText('Loading the set-up progress.').closest('[role="status"]')).toHaveAttribute('aria-busy', 'true');
    await screen.findByRole('list');
    expect(screen.queryByText('Loading the set-up progress.')).not.toBeInTheDocument();
  });

  it('browse: shows no reporter until one is chosen', async () => {
    render(<SetupTracker />);
    await screen.findByRole('list');
    expect(screen.queryByRole('region', { name: 'UCR West set-up' })).not.toBeInTheDocument();
  });

  it('opens a reporter in the address when its row is chosen, and marks the row as current', async () => {
    const user = userEvent.setup();
    render(<SetupTracker />);
    await user.click(await screen.findByRole('button', { name: /UCR West/ }));
    expect(nav.state.pushed).toEqual(['/lead/reporters?invitation=inv-1']);
    expect(await screen.findByRole('region', { name: 'UCR West set-up' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /UCR West/ })).toHaveAttribute('aria-current', 'true');
    expect(screen.getByRole('button', { name: /Reablement/ })).not.toHaveAttribute('aria-current');
  });

  it('opens the reporter named in the address, with the list still there', async () => {
    nav.set('invitation=inv-1');
    render(<SetupTracker />);
    const section = await screen.findByRole('region', { name: 'UCR West set-up' });
    expect(within(section).getByText('Stuck at: Notifications on.')).toBeInTheDocument();
    expect(within(section).getByText(/Invited 09:00, last seen 09:21\./)).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /Reablement/ })).toHaveLength(1);
  });

  it('says a complete set-up is complete, with its first report time', async () => {
    nav.set('invitation=inv-2');
    render(<SetupTracker />);
    const section = await screen.findByRole('region', { name: 'Reablement set-up' });
    expect(within(section).getByText('Complete. First report 10:12.')).toBeInTheDocument();
  });

  it('lists the seven steps of the open reporter, each done, waiting here or not done in words', async () => {
    nav.set('invitation=inv-1');
    render(<SetupTracker />);
    const list = await screen.findByRole('list', { name: 'Set-up steps' });
    expect(within(list).getAllByRole('listitem').map((item) => item.textContent)).toEqual([
      'Invited 09:00. Done.',
      'Number checked. Done.',
      'Channel chosen. Done.',
      'Installed. Done.',
      'Notifications on. Waiting here.',
      'PIN set. Not done.',
      'First report. Not done.',
    ]);
  });

  it('says so, in words, when the address names an invitation that is not in the list', async () => {
    nav.set('invitation=inv-nope');
    render(<SetupTracker />);
    expect(await screen.findByText('We could not find that invitation. Choose one from the list.')).toBeInTheDocument();
  });

  it('goes back to the list from the Back to the list button', async () => {
    const user = userEvent.setup();
    nav.set('invitation=inv-1');
    render(<SetupTracker />);
    await user.click(await screen.findByRole('button', { name: 'Back to the list' }));
    expect(nav.state.pushed).toEqual(['/lead/reporters']);
    expect(screen.queryByRole('region', { name: 'UCR West set-up' })).not.toBeInTheDocument();
  });

  it('resends the invitation through the resend route and says so in a status', async () => {
    const user = userEvent.setup();
    nav.set('invitation=inv-1');
    render(<SetupTracker />);
    await user.click(await screen.findByRole('button', { name: 'Resend the invitation' }));
    await vi.waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Invitation sent again.'));
    expect(seenLeadPosts[0]).toMatchObject({ path: '/api/bff/lead/invitations/inv-1/resend' });
  });

  it('says in an alert when the resend is refused', async () => {
    const user = userEvent.setup();
    server.use(http.post('/api/bff/lead/invitations/:id/resend', () => HttpResponse.json({ code: 'forbidden' }, { status: 403 })));
    nav.set('invitation=inv-1');
    render(<SetupTracker />);
    await user.click(await screen.findByRole('button', { name: 'Resend the invitation' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('You cannot do this. Ask a shift lead.');
  });

  it('switches a reporter to text, and offers to phone them', async () => {
    const user = userEvent.setup();
    nav.set('invitation=inv-1');
    render(<SetupTracker />);
    const section = await screen.findByRole('region', { name: 'UCR West set-up' });
    await user.click(within(section).getByRole('button', { name: 'Switch them to text' }));
    await vi.waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('They are switched to text.'));
    expect(seenLeadPosts[0]).toMatchObject({ path: '/api/bff/lead/invitations/inv-1/switch-to-text' });
    expect(within(section).getByRole('button', { name: 'Phone them' })).toBeInTheDocument();
  });

  it('records what the service said by phone for the invitation\'s own service, with no case', async () => {
    const user = userEvent.setup();
    nav.set('invitation=inv-1');
    render(<SetupTracker />);
    await user.click(await screen.findByRole('button', { name: 'Phone them' }));
    await user.click(screen.getByRole('button', { name: 'Not accepting' }));
    await user.click(screen.getByRole('button', { name: 'Save position' }));
    await vi.waitFor(() => expect(seenLeadPosts).toHaveLength(1));
    expect(seenLeadPosts[0]).toMatchObject({ path: '/api/bff/lead/services/s-ucr-west/phoned', body: { said: 'not-accepting' } });
  });

  it('empty: says no one has been invited, with a way to invite someone', async () => {
    server.use(http.get('/api/bff/lead/invitations', () => HttpResponse.json({ items: [] })));
    render(<SetupTracker />);
    expect(await screen.findByRole('heading', { level: 2, name: 'No one has been invited yet' })).toBeInTheDocument();
    expect(screen.getByText(/Invite the first person who reports capacity for a service/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Invite someone' })).toHaveAttribute('href', '/lead/reporters/invite');
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
  });

  it('error: says what happened and what to do, and loads again on Try again', async () => {
    const user = userEvent.setup();
    let calls = 0;
    server.use(
      http.get('/api/bff/lead/invitations', () => {
        calls += 1;
        return calls === 1 ? HttpResponse.json({ code: 'down' }, { status: 500 }) : HttpResponse.json({ items: [] });
      }),
    );
    render(<SetupTracker />);
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('We could not load set-up progress');
    expect(alert).toHaveTextContent('Nothing has been lost. Check your connection and try again.');
    await user.click(within(alert).getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('heading', { level: 2, name: 'No one has been invited yet' })).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(calls).toBe(2);
  });

  it('has no axe violations in browse', async () => {
    const { container } = render(<SetupTracker />);
    await screen.findByRole('list');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('has no axe violations with a reporter open', async () => {
    nav.set('invitation=inv-1');
    const { container } = render(<SetupTracker />);
    await screen.findByRole('region', { name: 'UCR West set-up' });
    expect(detail('UCR West set-up')).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
