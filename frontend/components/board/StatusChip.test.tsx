import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import type { BoardStatus } from '@/lib/board/types';
import { CHIP_SHAPES, CHIP_WORDS, LastKnownPill, StatusChip } from './StatusChip';

// Status is a shape plus a word, never colour alone (advisor-clinical-wall.md section 2, "Status language").
const SIX: [BoardStatus, string, string][] = [
  ['accepting', 'Accepting', 'circle'],
  ['limited', 'Limited', 'half-circle'],
  ['not-accepting', 'Not accepting', 'square'],
  ['over-capacity', 'Over capacity', 'triangle'],
  ['not-updated', 'Not updated', 'dashed-ring'],
  ['out-of-hours', 'Out of hours', 'crescent'],
];

describe('StatusChip', () => {
  it.each(SIX)('%s has the word %s and the shape %s', (status, word, shape) => {
    const { container } = render(<StatusChip status={status} />);
    const chip = container.querySelector<HTMLElement>('[data-status]');

    expect(chip).toHaveAttribute('data-status', status);
    expect(chip).toHaveAttribute('data-shape', shape);
    expect(chip).toHaveTextContent(new RegExp(`^${word}$`));
    expect(CHIP_WORDS[status]).toBe(word);
    expect(CHIP_SHAPES[status]).toBe(shape);
  });

  it('gives each of the six states its own shape and its own word', () => {
    expect(new Set(Object.values(CHIP_SHAPES)).size).toBe(6);
    expect(new Set(Object.values(CHIP_WORDS)).size).toBe(6);
  });

  it('draws the shape as an svg that is hidden from assistive technology, so the word carries the meaning', () => {
    const { container } = render(<StatusChip status="out-of-hours" />);
    const svg = container.querySelector('svg');

    expect(svg).toHaveAttribute('aria-hidden', 'true');
    expect(screen.getByText('Out of hours')).toBeInTheDocument();
  });

  it('tells Out of hours apart from Not accepting by word and shape', () => {
    const out = render(<StatusChip status="out-of-hours" />);
    const closed = render(<StatusChip status="not-accepting" />);

    expect(out.container.querySelector('[data-shape]')?.getAttribute('data-shape')).not.toBe(
      closed.container.querySelector('[data-shape]')?.getAttribute('data-shape'),
    );
    expect(out.container.textContent).not.toContain('Not accepting');
  });

  it('can carry a longer wording of the same state, for the key', () => {
    const { container } = render(<StatusChip status="limited" label="Limited: phone to confirm" />);

    expect(container.querySelector('[data-status="limited"]')).toHaveTextContent('Limited: phone to confirm');
    expect(container.querySelector('[data-shape="half-circle"]')).not.toBeNull();
  });

  it('has a large size for the wall', () => {
    const { container } = render(<StatusChip status="accepting" size="lg" />);

    expect(container.querySelector('[data-status]')).toHaveAttribute('data-size', 'lg');
  });

  it('has no accessibility violations in any of the six states', async () => {
    const { container } = render(
      <ul>
        {SIX.map(([status]) => (
          <li key={status}>
            <StatusChip status={status} />
          </li>
        ))}
      </ul>,
    );

    expect(container.querySelectorAll('[data-status]')).toHaveLength(6);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});

describe('LastKnownPill', () => {
  it('says Last known in words, as a dashed pill, and is not a status', () => {
    const { container } = render(<LastKnownPill />);

    expect(screen.getByText('Last known')).toBeInTheDocument();
    expect(container.querySelector('[data-overlay="last-known"]')).not.toBeNull();
    expect(container.querySelector('[data-status]')).toBeNull();
  });
});
