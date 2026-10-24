import { describe, expect, it } from 'vitest';
import RootLayout from './layout';

// The root layout returns the <html> element itself, so the attribute can be
// checked without a DOM. The browser check is in e2e/smoke.spec.ts.
describe('root layout', () => {
  it('sets the document language to en-GB', () => {
    const tree = RootLayout({ children: null });

    expect(tree.type).toBe('html');
    expect(tree.props.lang).toBe('en-GB');
  });
});
