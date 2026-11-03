import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { LinkFrame } from './LinkFrame';

// The public link pages' frame (artboards B3, B4): a light top bar with the mark and a "No login needed" tag,
// and a centred column.

describe('LinkFrame', () => {
  it('draws the top bar with the product name and the "No login needed" tag, then the page', async () => {
    const { container } = render(
      <LinkFrame>
        <main>
          <h1>The page</h1>
        </main>
      </LinkFrame>,
    );
    const bar = screen.getByRole('banner');
    expect(bar).toHaveTextContent('Overwatch');
    expect(bar).toHaveTextContent('No login needed');
    expect(screen.getByRole('heading', { name: 'The page' })).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('can leave the tag out (the booked and closed pages)', () => {
    render(
      <LinkFrame noLoginTag={false}>
        <p>Booked</p>
      </LinkFrame>,
    );
    expect(screen.getByRole('banner')).toHaveTextContent('Overwatch');
    expect(screen.queryByText('No login needed')).toBeNull();
  });

  it('hides the mark from a screen reader', () => {
    const { container } = render(
      <LinkFrame>
        <p>x</p>
      </LinkFrame>,
    );
    expect(container.querySelector('header svg')).toHaveAttribute('aria-hidden', 'true');
  });

  it('puts the page after the top bar', () => {
    render(
      <LinkFrame>
        <p>The page</p>
      </LinkFrame>,
    );
    expect(screen.getByRole('banner').compareDocumentPosition(screen.getByText('The page')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
