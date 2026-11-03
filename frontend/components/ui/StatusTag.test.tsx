import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { StatusTag, type StatusTagVariant } from './StatusTag';

// Shape plus word, never colour alone: each variant has its own shape (decorative) and the word the page gives.

const VARIANTS: readonly StatusTagVariant[] = ['done', 'waiting', 'todo', 'problem', 'live', 'closed', 'over', 'paused', 'confirmed', 'due'];

describe('StatusTag', () => {
  it.each(VARIANTS)('%s shows its word and a decorative shape', (variant) => {
    const { container } = render(<StatusTag variant={variant}>Word {variant}</StatusTag>);
    expect(screen.getByText(`Word ${variant}`)).toBeInTheDocument();
    const svg = container.querySelector('svg');
    expect(svg).not.toBeNull();
    expect(svg).toHaveAttribute('aria-hidden', 'true');
    expect(container.firstElementChild).toHaveAttribute('data-variant', variant);
  });

  it('has a different shape for each of the shape families (not colour alone)', () => {
    const shapes = new Map<string, string>();
    for (const variant of VARIANTS) {
      const { container, unmount } = render(<StatusTag variant={variant}>x</StatusTag>);
      shapes.set(variant, container.querySelector('svg')?.innerHTML ?? '');
      unmount();
    }
    const distinct = (a: StatusTagVariant, b: StatusTagVariant) => expect(shapes.get(a), `${a} vs ${b}`).not.toBe(shapes.get(b));
    distinct('done', 'waiting');
    distinct('done', 'todo');
    distinct('waiting', 'todo');
    distinct('done', 'problem');
    distinct('problem', 'closed');
    distinct('todo', 'paused');
    distinct('done', 'confirmed');
    distinct('waiting', 'due');
  });

  it('is named by its word alone', () => {
    const { container } = render(<StatusTag variant="problem">Needs attention</StatusTag>);
    expect(container.firstElementChild).toHaveTextContent(/^Needs attention$/);
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <ul>
        {VARIANTS.map((v) => (
          <li key={v}>
            <StatusTag variant={v}>{v}</StatusTag>
          </li>
        ))}
      </ul>,
    );
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
