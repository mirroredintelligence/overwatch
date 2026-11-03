import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { StatusTile, type TileStatus } from './StatusTile';

// The large tile on every board. Status is a glyph, a word and a colour; a stale figure is dashed; an over-capacity
// tile is hatched. The word is the status, so the tests look for the words a person reads.

const STATUSES: readonly TileStatus[] = ['accepting', 'limited', 'not-accepting', 'over-capacity', 'not-updated'];

const WORDS: Record<TileStatus, string> = {
  accepting: 'Accepting',
  limited: 'Limited',
  'not-accepting': 'Not accepting',
  'over-capacity': 'Over capacity',
  'not-updated': 'Not updated',
};

function tile(overrides: Partial<Parameters<typeof StatusTile>[0]> = {}) {
  return (
    <StatusTile
      name="UCR West"
      organisation="Community Trust · Urgent community response"
      status="accepting"
      figure="4"
      figureLabel="referrals in the next 2 hrs"
      updated="Updated 4 minutes ago"
      {...overrides}
    />
  );
}

describe('StatusTile', () => {
  it('shows the name as a level 3 heading, the organisation, the figure, its label and the update time', () => {
    render(tile());
    expect(screen.getByRole('heading', { level: 3, name: 'UCR West' })).toBeInTheDocument();
    expect(screen.getByText('Community Trust · Urgent community response')).toBeInTheDocument();
    expect(screen.getByText('4')).toBeInTheDocument();
    expect(screen.getByText('referrals in the next 2 hrs')).toBeInTheDocument();
    expect(screen.getByText('Updated 4 minutes ago')).toBeInTheDocument();
  });

  it.each(STATUSES)('%s shows its word from the status badge, in words and not colour alone', (status) => {
    const { container } = render(tile({ status }));
    expect(screen.getByText(WORDS[status])).toBeInTheDocument();
    expect(container.firstElementChild).toHaveAttribute('data-status', status);
    const svg = container.querySelector('svg');
    expect(svg).toHaveAttribute('aria-hidden', 'true');
  });

  it('uses the foundation status tag for the chip: filled for accepting, half for limited, over for over capacity', () => {
    const { container, unmount } = render(tile({ status: 'accepting' }));
    expect(container.querySelector('[data-variant="live"]')).not.toBeNull();
    unmount();
    const limited = render(tile({ status: 'limited' }));
    expect(limited.container.querySelector('[data-variant="waiting"]')).not.toBeNull();
    limited.unmount();
    const over = render(tile({ status: 'over-capacity' }));
    expect(over.container.querySelector('[data-variant="over"]')).not.toBeNull();
  });

  it('shows the not-updated figure as a question mark with its label, never as a current number', () => {
    render(tile({ status: 'not-updated', figure: '?', figureLabel: 'Phone to confirm', updated: 'Not updated for 4 hrs 10 min' }));
    expect(screen.getByText('?')).toBeInTheDocument();
    expect(screen.getByText('Phone to confirm')).toBeInTheDocument();
    expect(screen.getByText('Not updated for 4 hrs 10 min')).toBeInTheDocument();
  });

  it('marks the tile as the user organisation only when it is theirs', () => {
    const { unmount } = render(tile({ own: true }));
    expect(screen.getByText('Your organisation')).toBeInTheDocument();
    unmount();
    render(tile({ own: false }));
    expect(screen.queryByText('Your organisation')).toBeNull();
  });

  it('renders children under the figure, for a service line link', () => {
    render(
      tile({
        children: <a href="tel:01632960001">Service line 01632 960001</a>,
      }),
    );
    expect(screen.getByRole('link', { name: 'Service line 01632 960001' })).toHaveAttribute('href', 'tel:01632960001');
  });

  it('keeps the heading name free of the organisation pill', () => {
    render(tile({ own: true }));
    expect(screen.getByRole('heading', { name: 'UCR West' })).toBeInTheDocument();
  });

  it('has no axe violations for any status', async () => {
    const { container } = render(
      <ul>
        {STATUSES.map((s) => (
          <li key={s}>{tile({ status: s, name: `Service ${s}` })}</li>
        ))}
      </ul>,
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('draws over capacity hatched and not updated dashed, in tokens only', () => {
    const css = readFileSync(resolve(__dirname, 'StatusTile.module.css'), 'utf8');
    const bare = css.replace(/\/\*[\s\S]*?\*\//g, '');
    expect(bare).toMatch(/\.over[\s\S]*?repeating-linear-gradient/);
    expect(bare).toMatch(/\.notUpdated[\s\S]*?dashed/);
    expect(bare).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(bare).not.toMatch(/\b(rgb|rgba|hsl|hsla)\(/);
    expect(bare).toMatch(/var\(--c-/);
  });
});
