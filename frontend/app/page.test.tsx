import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { PRODUCT_NAME } from '@/lib/product';
import HomePage from './page';

// The root page is the same for every host: it names the product and nothing about an organisation.
describe('root page', () => {
  it('has one heading, the product name', () => {
    render(<HomePage />);
    expect(screen.getByRole('heading', { level: 1, name: PRODUCT_NAME })).toBeInTheDocument();
  });

  it('names no place, organisation, service, phone number or postcode', () => {
    const { container } = render(<HomePage />);
    const text = container.textContent ?? '';
    expect(text).not.toMatch(/dorset|trust|spoa|single point|nhs|icb|\d{5}|[A-Z]{1,2}\d{1,2} ?\d[A-Z]{2}/i);
  });

  it('reads nothing from a request: it renders with no session, cookie or header', () => {
    expect(() => render(<HomePage />)).not.toThrow();
  });
});
