import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { ReplyByTag } from './ReplyByTag';

// Artboards B1, B2, B7, D1: a clock and "Reply by 10:30". A fixed time, never a countdown.

describe('ReplyByTag', () => {
  it('says "Reply by" and the time it is given', () => {
    render(<ReplyByTag time="10:30" dataEl="TAG" />);
    const tag = screen.getByText('Reply by 10:30');
    expect(tag).toHaveAttribute('data-el', 'TAG');
  });

  it('draws the clock as a picture only, so the words carry the meaning', () => {
    const { container } = render(<ReplyByTag time="10:30" />);
    const svg = container.querySelector('svg');
    expect(svg).not.toBeNull();
    expect(svg).toHaveAttribute('aria-hidden', 'true');
    expect(screen.queryByRole('img')).toBeNull();
  });

  it('is static: no timer element and no live region', () => {
    const { container } = render(<ReplyByTag time="08:30" />);
    expect(container.querySelector('time, [aria-live], [role="timer"]')).toBeNull();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<ReplyByTag time="10:30" />);
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
