import { render, screen } from '@testing-library/react';
import { axe } from 'vitest-axe';
import { describe, expect, it } from 'vitest';
import WallScreenPage from './page';

describe('wall screen page', () => {
  it('shows the wall screen heading and the no-patient-information line', () => {
    render(<WallScreenPage />);

    expect(
      screen.getByRole('heading', { name: 'DIUCS capacity wall screen' }),
    ).toBeInTheDocument();
    expect(
      screen.getByText('No patient information on this screen'),
    ).toBeInTheDocument();
  });

  it('has no accessibility violations', async () => {
    const { container } = render(<WallScreenPage />);

    expect(await axe(container)).toHaveNoViolations();
  });
});
