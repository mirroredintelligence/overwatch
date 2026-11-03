import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import OfflinePage from './page';

describe('offline page', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('says there is no connection and what to do instead, and passes axe', async () => {
    const { container } = render(<OfflinePage />);
    expect(screen.getByRole('heading', { level: 1, name: 'No connection' })).toBeInTheDocument();
    expect(
      screen.getByText(
        'Capacity cannot be shown without a connection. Use the phone process: phone the coordination team on the number your service has on record.',
      ),
    ).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('says nothing shown is current, and that a figure that cannot be refreshed is never shown as current', () => {
    render(<OfflinePage />);
    expect(screen.getByText('Nothing shown here is current.')).toBeInTheDocument();
    expect(
      screen.getByText('A figure that cannot be refreshed is never shown as if it were.', { exact: false }),
    ).toBeInTheDocument();
  });

  it('has a Try again button that reloads the page', () => {
    const reload = vi.fn();
    vi.stubGlobal('location', { ...window.location, reload });
    render(<OfflinePage />);
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(reload).toHaveBeenCalledTimes(1);
  });
});
