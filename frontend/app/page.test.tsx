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

  it('shows the name as the heading text, not as an image', () => {
    render(<HomePage />);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(PRODUCT_NAME);
    expect(screen.queryByRole('img')).toBeNull();
  });

  it('draws the mark as decoration, hidden from assistive technology', () => {
    const { container } = render(<HomePage />);
    const mark = container.querySelector('svg');
    expect(mark).not.toBeNull();
    expect(mark).toHaveAttribute('aria-hidden', 'true');
  });

  it('shows the one-line description under the name', () => {
    render(<HomePage />);
    expect(
      screen.getByText('The live picture of which urgent care services can take a patient right now.'),
    ).toBeInTheDocument();
  });

  it('offers the staff sign-in and the platform console as links', () => {
    render(<HomePage />);
    expect(screen.getByRole('link', { name: 'Sign in' })).toHaveAttribute('href', '/sign-in');
    expect(screen.getByRole('link', { name: 'Platform console' })).toHaveAttribute('href', '/operator');
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
