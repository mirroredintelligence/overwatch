import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import AdvisorV2Page from './page';

// The Advisor v2 landing page (DEC-1362): a placeholder heading; the finder comes later.
describe('the Advisor v2 landing page', () => {
  it('has a heading', () => {
    render(<AdvisorV2Page />);
    expect(screen.getByRole('heading', { level: 1, name: 'Advisor v2' })).toBeInTheDocument();
  });
});
