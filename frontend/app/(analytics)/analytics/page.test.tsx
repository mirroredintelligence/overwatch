import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import AnalyticsPage from './page';

// The Analytics User's landing page (DEC-1362): a placeholder heading; the overview comes later. It reads nothing.
describe('the analytics landing page', () => {
  it('has a heading and shows no case, patient or postcode', () => {
    render(<AnalyticsPage />);
    expect(screen.getByRole('heading', { level: 1, name: 'Analytics' })).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/postcode|patient|case/i);
  });
});
