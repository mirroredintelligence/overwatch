import { render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { BfcacheGuard } from './BfcacheGuard';

function pageshow(persisted: boolean) {
  const event = new Event('pageshow');
  Object.defineProperty(event, 'persisted', { value: persisted });
  window.dispatchEvent(event);
}

describe('BfcacheGuard', () => {
  it('renders nothing', () => {
    const { container } = render(<BfcacheGuard reload={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('reloads a page the back-forward cache restored', () => {
    const reload = vi.fn();
    render(<BfcacheGuard reload={reload} />);
    pageshow(true);
    expect(reload).toHaveBeenCalledOnce();
  });

  it('does not reload an ordinary page show', () => {
    const reload = vi.fn();
    render(<BfcacheGuard reload={reload} />);
    pageshow(false);
    expect(reload).not.toHaveBeenCalled();
  });

  it('stops listening when it is removed', () => {
    const reload = vi.fn();
    const { unmount } = render(<BfcacheGuard reload={reload} />);
    unmount();
    pageshow(true);
    expect(reload).not.toHaveBeenCalled();
  });
});
