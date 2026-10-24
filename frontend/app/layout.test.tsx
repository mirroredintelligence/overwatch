import { describe, expect, it, vi } from 'vitest';

// next/font/google fetches the font at build time, so the test replaces it with
// a stub that records the options the layout passes.
const atkinson = vi.hoisted(() => ({
  Atkinson_Hyperlegible: vi.fn(() => ({ className: 'atkinson-class', variable: 'atkinson-var' })),
}));
vi.mock('next/font/google', () => atkinson);

import RootLayout from './layout';

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
