import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { MyServices } from './MyServices';

describe('MyServices', () => {
  it('says how to add a service and passes axe', async () => {
    const { container } = render(<MyServices />);
    expect(await screen.findByRole('heading', { name: 'My services' })).toBeInTheDocument();
    expect(
      screen.getByText('To add a service, ask the SPOA shift lead. New services are added by invitation and checked.'),
    ).toBeInTheDocument();
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
