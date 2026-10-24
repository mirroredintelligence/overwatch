import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { contrastRatio } from '@/lib/a11y/contrast';
import { STATUS_LABELS, StatusBadge, type StatusCode } from './StatusBadge';

const ALL: StatusCode[] = [
  'accepting',
  'limited',
  'not-accepting',
  'over-capacity',
  'not-updated',
  'out-of-hours',
  'last-known',
];

const WORDS: Record<StatusCode, string> = {
  accepting: 'Accepting',
  limited: 'Limited',
  'not-accepting': 'Not accepting',
  'over-capacity': 'Over capacity',
  'not-updated': 'Not updated',
  'out-of-hours': 'Out of hours',
  'last-known': 'Last known',
};

// Text and background of each chip, as the token values in tokens.css.
const CHIP_PAIRS: [StatusCode, string, string][] = [
  ['accepting', '#FFFFFF', '#0B5C8C'],
  ['limited', '#FFFFFF', '#A34700'],
  ['not-accepting', '#FFFFFF', '#3A4750'],
  ['over-capacity', '#FFFFFF', '#6B2C91'],
  ['out-of-hours', '#FFFFFF', '#3A4750'],
  ['not-updated', '#26343B', '#FFFFFF'],
  ['last-known', '#26343B', '#FFFFFF'],
];

describe('STATUS_LABELS', () => {
  it('holds the agreed word for every status', () => {
    expect(STATUS_LABELS).toEqual(WORDS);
  });
});

describe.each(ALL)('StatusBadge with status %s', (status) => {
  it('renders the exact word from STATUS_LABELS', () => {
    render(<StatusBadge status={status} />);
    expect(screen.getByText(WORDS[status])).toBeInTheDocument();
  });

  it('marks its icon aria-hidden so the word carries the meaning', () => {
    const { container } = render(<StatusBadge status={status} />);
    const icon = container.querySelector('svg');
    expect(icon).not.toBeNull();
    expect(icon).toHaveAttribute('aria-hidden', 'true');
  });

  it('exposes its status code as data-status', () => {
    const { container } = render(<StatusBadge status={status} />);
    expect(container.querySelector('[data-status]')).toHaveAttribute('data-status', status);
  });
});

describe('StatusBadge shapes', () => {
  it('gives six distinct shapes, with not-updated and last-known sharing the dashed one', () => {
    const shapes = new Map<StatusCode, string | null>();
    for (const status of ALL) {
      const { container, unmount } = render(<StatusBadge status={status} />);
      shapes.set(status, container.querySelector('[data-shape]')?.getAttribute('data-shape') ?? null);
      unmount();
    }

    expect(new Set(shapes.values()).size).toBe(6);
    expect(shapes.get('not-updated')).not.toBeNull();
    expect(shapes.get('not-updated')).toBe(shapes.get('last-known'));
  });
});

describe('StatusBadge sizes', () => {
  it('defaults to sm', () => {
    const { container } = render(<StatusBadge status="accepting" />);
    expect(container.querySelector('[data-status]')).toHaveAttribute('data-size', 'sm');
  });

  it('renders lg when asked', () => {
    const { container } = render(<StatusBadge status="accepting" size="lg" />);
    expect(container.querySelector('[data-status]')).toHaveAttribute('data-size', 'lg');
  });
});

describe('chip colour pairs', () => {
  it.each(CHIP_PAIRS)('%s text meets WCAG AA 4.5:1', (_status, fg, bg) => {
    expect(contrastRatio(fg, bg)).toBeGreaterThanOrEqual(4.5);
  });
});

describe('StatusBadge accessibility', () => {
  it('has no axe violations for a list of all badges', async () => {
    const { container } = render(
      <ul>
        {ALL.map((status) => (
          <li key={status}>
            <StatusBadge status={status} />
          </li>
        ))}
      </ul>,
    );
    expect(container.querySelectorAll('[data-status]')).toHaveLength(ALL.length);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
