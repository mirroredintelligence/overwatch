import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { entry, GENERATED_AT } from '@/test/fixtures/board';
import { Tile } from './Tile';

// TEN-072 (docs/design/network-ui.md section 6, WallNetwork): a tile of a network's board on a wall keeps the
// wall tile's look and its WALL-TILE id, with the organisation under the service name, and shows a paused
// listing as it is: no figure, "Phone to confirm".

const NETWORK_ENTRY = entry({ serviceId: 'lst-0002', name: 'Virtual ward frailty', organisation: 'Sample Area B', ownOrganisation: false, pending: 0, comment: null, nextDueAt: null });

describe('Tile: a network row on the wall', () => {
  it('has the organisation under the service name, and keeps the WALL-TILE id', () => {
    const { container } = render(<Tile entry={NETWORK_ENTRY} now={GENERATED_AT} />);
    const tile = container.querySelector('[data-el="WALL-TILE"]') as HTMLElement;
    expect(tile).not.toBeNull();
    expect(within(tile).getByRole('heading', { name: 'Virtual ward frailty' })).toBeInTheDocument();
    expect(within(tile).getByText('Sample Area B')).toBeInTheDocument();
    expect(within(tile).queryByText('Your organisation')).not.toBeInTheDocument();
  });

  it('marks the viewer’s own organisation in words', () => {
    render(<Tile entry={{ ...NETWORK_ENTRY, ownOrganisation: true, organisation: 'Own Trust' }} now={GENERATED_AT} />);
    expect(screen.getByText('Own Trust')).toBeInTheDocument();
    expect(screen.getByText('Your organisation')).toBeInTheDocument();
  });

  it('has no organisation line on the wall’s own board', () => {
    const { container } = render(<Tile entry={entry({ serviceId: 's', name: 'UCR West' })} now={GENERATED_AT} />);
    expect(container.querySelector('[data-el="WALL-TILE"]')?.textContent).not.toContain('Your organisation');
  });

  it('shows a paused listing with no figure and says it is not available on the network', () => {
    const { container } = render(
      <Tile entry={{ ...NETWORK_ENTRY, paused: true, status: 'not-updated', effectiveAvailable: null, used: null, reportedAt: null, unitLabel: 'Phone to confirm' }} now={GENERATED_AT} />,
    );
    const tile = container.querySelector('[data-el="WALL-TILE"]') as HTMLElement;
    expect(within(tile).getByText('?')).toBeInTheDocument();
    expect(within(tile).getAllByText('Phone to confirm').length).toBeGreaterThan(0);
    expect(within(tile).getByText('Not available on the network. Phone to confirm.')).toBeInTheDocument();
    expect(tile).toHaveAttribute('data-status', 'not-updated');
    expect(tile.querySelector('[data-bar-fill]')).toBeNull();
  });

  it('draws a paused listing as Not updated (dashed ring), not as a current state, and without the Last known pill', () => {
    const { container } = render(
      <Tile entry={{ ...NETWORK_ENTRY, paused: true, status: 'accepting', effectiveAvailable: null, used: null }} now={GENERATED_AT} />,
    );
    const tile = container.querySelector('[data-el="WALL-TILE"]') as HTMLElement;
    expect(tile.querySelector('[data-status="not-updated"][data-shape="dashed-ring"]')).toHaveTextContent('Not updated');
    expect(tile.querySelector('[data-shape="circle"]')).toBeNull();
    expect(tile.querySelector('[data-overlay="last-known"]')).toBeNull();
  });

  it('shows the organisation in the last known state too, with the Last known pill', () => {
    const { container } = render(<Tile entry={NETWORK_ENTRY} now={GENERATED_AT} lastKnown />);
    expect(screen.getByText('Sample Area B')).toBeInTheDocument();
    expect(screen.getByText('Do not rely on this. Phone to confirm.')).toBeInTheDocument();
    expect(container.querySelector('[data-overlay="last-known"]')).toHaveTextContent('Last known');
  });
});
