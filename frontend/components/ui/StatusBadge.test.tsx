import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
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

// The chip colours are read from the shipped CSS, not copied here, so a change
// to StatusBadge.module.css or tokens.css is what the contrast test sees.
const tokensCss = readFileSync(resolve(__dirname, '../../app/tokens.css'), 'utf8');
const badgeCss = readFileSync(resolve(__dirname, 'StatusBadge.module.css'), 'utf8');

const TOKEN_DECLARATION = /(?<![\w-])(--[\w-]+)\s*:\s*([^;]+);/g;
const tokenValues = new Map<string, string>();
for (const match of tokensCss.matchAll(TOKEN_DECLARATION)) {
  tokenValues.set(match[1], match[2].trim());
}

// Resolves a colour value from a declaration: var(--token) or a six-digit hex.
// Anything else throws, so an unreadable colour fails the test instead of
// being skipped.
function resolveColour(value: string): string {
  const variable = /^var\((--[\w-]+)\)$/.exec(value);
  const colour = variable ? tokenValues.get(variable[1]) : value;
  if (colour === undefined || !/^#[0-9a-f]{6}$/i.test(colour)) {
    throw new Error(`cannot resolve colour "${value}"`);
  }
  return colour;
}

// Collects the declarations of every rule whose selector list names
// `.<status>`, so grouped selectors such as ".not-accepting, .out-of-hours"
// are read for both statuses.
function declarationsFor(status: StatusCode): Map<string, string> {
  const found = new Map<string, string>();
  for (const rule of badgeCss.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const selectors = rule[1].split(',').map((s) => s.trim());
    if (!selectors.includes(`.${status}`)) continue;
    for (const decl of rule[2].matchAll(/([\w-]+)\s*:\s*([^;]+);/g)) {
      found.set(decl[1], decl[2].trim());
    }
  }
  return found;
}

// Text colour and background of each chip, read from the CSS.
const CHIP_PAIRS: [StatusCode, string, string][] = ALL.map((status) => {
  const decls = declarationsFor(status);
  const background = decls.get('background') ?? decls.get('background-color');
  const text = decls.get('color');
  if (background === undefined || text === undefined) {
    throw new Error(`no background and colour for ${status} in StatusBadge.module.css`);
  }
  return [status, resolveColour(text), resolveColour(background)];
});

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
  it('reads a text and background pair for every status from the CSS', () => {
    expect(CHIP_PAIRS.map(([status]) => status)).toEqual(ALL);
  });

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
