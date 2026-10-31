import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { BOARD_A, GENERATED_AT } from '@/test/fixtures/board';
import type { WallScope } from '@/lib/board/scope';
import { Board } from './Board';

// TEN-072 (docs/design/network-ui.md sections 5 and 6, WallNetwork and NetworkWallFallback): the wall board in
// network mode says "Showing: Network, {name}" in the header (there is no address bar), has the network's name
// as its heading, and no sorting footer; a wall that fell back says so in a warning and shows its own board.

const NETWORK: WallScope = { boardScope: 'network', scopeVersion: 3, fallback: false, networkName: 'West Dorset system' };
const FELL_BACK: WallScope = { boardScope: 'tenant', scopeVersion: 4, fallback: true, networkName: null };
const LAST_KNOWN = { mode: 'last-known' as const, reason: 'offline' as const, since: GENERATED_AT, asOf: GENERATED_AT, now: GENERATED_AT, ageMs: 0 };

describe('Board: network mode', () => {
  it('says which network it shows in the header, with no switch', () => {
    render(<Board board={BOARD_A} scope={NETWORK} />);
    const header = screen.getByRole('region', { name: 'Which board you are viewing' });
    expect(header).toHaveTextContent('Showing: Network, West Dorset system');
    expect(screen.queryByRole('navigation')).toBeNull();
  });

  it('has the network’s name as its heading, whatever heading the tenant has', () => {
    render(<Board board={BOARD_A} scope={NETWORK} heading="Dorset Capacity A" />);
    expect(screen.getByRole('heading', { level: 1, name: 'West Dorset system capacity' })).toBeInTheDocument();
    expect(document.body.textContent).not.toContain('Dorset Capacity A');
  });

  it('has no sorting line in its footer, and still says no patient information is on the screen', () => {
    render(<Board board={BOARD_A} scope={NETWORK} />);
    expect(document.body.textContent).not.toMatch(/Sorted by|Not ranked/);
    expect(screen.getByText('No patient information on this screen')).toBeInTheDocument();
  });

  it('keeps saying which network it shows when the figures are last known', () => {
    render(<Board board={BOARD_A} scope={NETWORK} lastKnown={LAST_KNOWN} />);
    expect(screen.getByText('Showing: Network, West Dorset system')).toBeInTheDocument();
  });

  it('shows no network name and no fallback notice on its own board', () => {
    render(<Board board={BOARD_A} scope={{ boardScope: 'tenant', scopeVersion: 1, fallback: false, networkName: null }} />);
    expect(screen.getByText('Showing: Our organisation')).toBeInTheDocument();
    expect(screen.queryByText(/No longer showing/)).toBeNull();
  });
});

describe('Board: the wall fell back (NetworkWallFallback)', () => {
  it('says so in a warning that names the network it was showing, and shows its own board', () => {
    render(<Board board={BOARD_A} scope={FELL_BACK} fellBackFrom="West Dorset system" />);
    const notice = screen.getByRole('alert');
    expect(notice).toHaveTextContent('No longer showing West Dorset system. Showing: Our organisation.');
    expect(notice).toHaveAttribute('data-el', 'SCOPE-BANNER-NOTICE');
    expect(notice).toHaveAttribute('data-tone', 'warning');
    expect(screen.getByRole('region', { name: 'Which board you are viewing' })).toHaveTextContent('Showing: Our organisation');
  });

  it('says it without a name when the screen never showed the network in this session', () => {
    render(<Board board={BOARD_A} scope={FELL_BACK} fellBackFrom={null} />);
    expect(screen.getByRole('alert')).toHaveTextContent('No longer showing the network board. Showing: Our organisation.');
  });

  it('keeps the warning when the figures are last known', () => {
    render(<Board board={BOARD_A} scope={FELL_BACK} fellBackFrom="West Dorset system" lastKnown={LAST_KNOWN} />);
    expect(screen.getByText(/No longer showing West Dorset system/)).toBeInTheDocument();
  });

  it('has no axe violations in either state', async () => {
    const network = render(<Board board={BOARD_A} scope={NETWORK} />);
    expect(await runAxe(network.container)).toHaveNoViolations();
    network.unmount();
    const fell = render(<Board board={BOARD_A} scope={FELL_BACK} fellBackFrom="West Dorset system" />);
    expect(await runAxe(fell.container)).toHaveNoViolations();
  });
});
