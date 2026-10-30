import { describe, expect, it, vi } from 'vitest';

// next/font/google fetches the font at build time, so the test replaces it with
// a stub that records the options the layout passes.
const atkinson = vi.hoisted(() => ({
  Atkinson_Hyperlegible: vi.fn(() => ({ className: 'atkinson-class', variable: 'atkinson-var' })),
}));
vi.mock('next/font/google', () => atkinson);

import { PRODUCT_NAME } from '@/lib/product';
import RootLayout, { metadata } from './layout';

// The root layout returns the <html> element itself, so the attribute can be
// checked without a DOM. The browser check is in e2e/smoke.spec.ts.
describe('root layout', () => {
  it('sets the document language to en-GB', () => {
    const tree = RootLayout({ children: null });

    expect(tree.type).toBe('html');
    expect(tree.props.lang).toBe('en-GB');
  });

  it('loads Atkinson Hyperlegible into the --font-atkinson variable', () => {
    const tree = RootLayout({ children: null });

    expect(atkinson.Atkinson_Hyperlegible).toHaveBeenCalledWith(
      expect.objectContaining({ subsets: ['latin'], weight: ['400', '700'], variable: '--font-atkinson' }),
    );
    expect(tree.props.className).toBe('atkinson-var');
  });
});


// TEN-045: the page title and description name the product, never a place, an organisation or a
// service. An organisation's own name comes from its profile (TEN-049), not from this file.
describe('root layout metadata (TEN-045)', () => {
  it('names the product with one constant', () => {
    expect(PRODUCT_NAME).toBe('DIUCS capacity');
  });

  it('has the product name as the default title and as the end of the template a page title is put in', () => {
    expect(metadata.title).toEqual({ default: PRODUCT_NAME, template: `%s | ${PRODUCT_NAME}` });
  });

  it('has a description that is neutral: no place, organisation, service or system name', () => {
    expect(metadata.description).toBeTruthy();
    expect(String(metadata.description)).not.toMatch(/dorset|trust|spoa|single point|nhs|icb|systmone/i);
  });

  it('keeps the language en-GB, which is the default of every tenant profile', () => {
    expect(RootLayout({ children: null }).props.lang).toBe('en-GB');
  });
});
