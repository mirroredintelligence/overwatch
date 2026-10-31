import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { NetworkUnavailable } from './NetworkUnavailable';

// TEN-070 (docs/design/network-ui.md section 5): the states in which the network is not shown. One
// wording for every refusal, so the words never tell whether a network exists; the others name the network
// and say what to do next. No state blocks navigation, and the scope header stays wherever a network is
// named.

const OWN = '/advisor/board';

describe('not available (every refusal reads the same)', () => {
  it('says the view is not available, asks the viewer to ask their administrator, and links back to their own board', () => {
    render(<NetworkUnavailable reason="not-available" ownHref={OWN} />);
    const panel = screen.getByRole('status');
    expect(panel).toHaveAttribute('data-el', 'NET-STATE-PANEL');
    expect(panel).toHaveTextContent('Network view not available');
    expect(panel).toHaveTextContent('Ask your administrator.');
    const back = screen.getByRole('link', { name: 'Back to our organisation' });
    expect(back).toHaveAttribute('href', OWN);
    expect(back).toHaveAttribute('data-el', 'NET-STATE-BACK-LINK');
  });

  it('names no network, no organisation and no reason, and has no scope header (there is no network to name)', () => {
    const { container } = render(<NetworkUnavailable reason="not-available" ownHref={OWN} />);
    expect(screen.queryByRole('region', { name: 'Which board you are viewing' })).toBeNull();
    expect(container.textContent).not.toMatch(/forbidden|not found|left|paused|member|net-/i);
  });
});

describe('paused', () => {
  it('names the network, says to phone services, offers to try again, and keeps the scope header', async () => {
    const onRetry = vi.fn();
    render(<NetworkUnavailable reason="paused" networkName="Sample Network" ownHref={OWN} onRetry={onRetry} />);
    expect(screen.getByRole('status')).toHaveTextContent('The network view is paused');
    expect(screen.getByRole('status')).toHaveTextContent('Sample Network is not sharing capacity at the moment. Phone services to check.');
    expect(screen.getByText('Showing: Network, Sample Network')).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});

describe('membership ended', () => {
  it('says the organisation has left, and offers the history only', () => {
    render(<NetworkUnavailable reason="membership-ended" networkName="Sample Network" ownHref={OWN} historyHref="/network/history" endedOn="2026-10-01T09:00:00+00:00" />);
    expect(screen.getByRole('status')).toHaveTextContent('Your organisation has left Sample Network');
    expect(screen.getByRole('status')).toHaveTextContent('You can see the history of what was shared until 1 October 2026.');
    expect(screen.getByRole('link', { name: 'See history' })).toHaveAttribute('href', '/network/history');
    expect(screen.getByRole('link', { name: 'See history' })).toHaveAttribute('data-el', 'NET-BOARD-HISTORY-LINK');
  });

  it('says it without a date when it has none', () => {
    render(<NetworkUnavailable reason="membership-ended" networkName="Sample Network" ownHref={OWN} historyHref="/network/history" />);
    expect(screen.getByRole('status')).toHaveTextContent('You can see the history of what was shared.');
  });
});

describe('offline with nothing to keep', () => {
  it('says the board is offline and to use the whiteboard and phone process, and offers to try again', async () => {
    const onRetry = vi.fn();
    render(<NetworkUnavailable reason="offline" networkName="Sample Network" ownHref={OWN} onRetry={onRetry} since="2026-10-23T13:05:00Z" />);
    const panel = screen.getByRole('alert');
    expect(panel).toHaveAttribute('data-el', 'NET-STATE-PANEL');
    expect(panel).toHaveTextContent('Network board offline since 14:05');
    expect(panel).toHaveTextContent('Use the whiteboard and phone process.');
    expect(screen.getByText('Showing: Network, Sample Network')).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});

describe('every state', () => {
  it('has no axe violations', async () => {
    for (const element of [
      <NetworkUnavailable key="a" reason="not-available" ownHref={OWN} />,
      <NetworkUnavailable key="b" reason="paused" networkName="Sample Network" ownHref={OWN} onRetry={() => undefined} />,
      <NetworkUnavailable key="c" reason="membership-ended" networkName="Sample Network" ownHref={OWN} historyHref="/network/history" />,
      <NetworkUnavailable key="d" reason="offline" networkName="Sample Network" ownHref={OWN} onRetry={() => undefined} since="2026-10-23T13:05:00Z" />,
    ]) {
      const { container, unmount } = render(<main>{element}</main>);
      expect((await runAxe(container)).violations).toEqual([]);
      unmount();
    }
  });
});
