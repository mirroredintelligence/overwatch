import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import OfflinePage from './page';

describe('offline page', () => {
  it('says there is no connection and what to do instead, and passes axe', async () => {
    const { container } = render(<OfflinePage />);
    expect(screen.getByRole('heading', { level: 1, name: 'No connection' })).toBeInTheDocument();
    expect(
      screen.getByText(
        'Capacity cannot be shown without a connection. Use the phone process: phone the SPOA on the number your service has on record.',
      ),
    ).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
