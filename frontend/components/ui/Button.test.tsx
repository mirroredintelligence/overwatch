import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { Button } from './Button';

describe('Button', () => {
  it('renders a primary button with its text', () => {
    render(<Button variant="primary">Request</Button>);
    const el = screen.getByRole('button', { name: 'Request' });
    expect(el.tagName).toBe('BUTTON');
    expect(el).toHaveAttribute('data-variant', 'primary');
  });

  it('busy disables the button, sets aria-busy, and a click does nothing', async () => {
    const onClick = vi.fn();
    render(
      <Button variant="primary" busy onClick={onClick}>
        Request
      </Button>,
    );
    const el = screen.getByRole('button', { name: 'Request' });
    expect(el).toBeDisabled();
    expect(el).toHaveAttribute('aria-busy', 'true');
    await userEvent.click(el);
    expect(onClick).not.toHaveBeenCalled();
  });

  it('is not busy by default and click works', async () => {
    const onClick = vi.fn();
    render(<Button variant="secondary" onClick={onClick}>Go</Button>);
    const el = screen.getByRole('button', { name: 'Go' });
    expect(el).not.toHaveAttribute('aria-busy');
    expect(el).toBeEnabled();
    await userEvent.click(el);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('renders a link when href is given', () => {
    render(<Button variant="neutral" href="/board">Back</Button>);
    const el = screen.getByRole('link', { name: 'Back' });
    expect(el).toHaveAttribute('href', '/board');
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('renders data-el for every variant', () => {
    render(
      <>
        <Button variant="primary" dataEl="A">a</Button>
        <Button variant="secondary" dataEl="B">b</Button>
        <Button variant="neutral" dataEl="C" href="/x">c</Button>
      </>,
    );
    for (const id of ['A', 'B', 'C']) {
      expect(document.querySelector(`[data-el="${id}"]`)).not.toBeNull();
    }
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <main>
        <Button variant="primary">One</Button>
        <Button variant="secondary" href="/x">Two</Button>
        <Button variant="neutral" busy>Three</Button>
      </main>,
    );
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
