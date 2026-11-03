import { describe, expect, it, vi } from 'vitest';

// next/font/google fetches the font at build time, so the test replaces it with
// a stub that records the options the layout passes.
const atkinson = vi.hoisted(() => ({
  Atkinson_Hyperlegible: vi.fn(() => ({ className: 'atkinson-class', variable: 'atkinson-var' })),
}));
vi.mock('next/font/google', () => atkinson);

import { PRODUCT_NAME } from '@/lib/product';
import RootLayout, { metadata } from './layout';

vi.mock('next/headers', async () => {
  const m = await import('@/test/cookies');
  return { cookies: m.cookiesMock, headers: m.headersMock };
});

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


// TEN-045 and DEC-1328: the page title and description name the product, never an organisation or a place.
// The host is one domain for every staff person, so no host's profile name may reach the title.
describe('root layout metadata (TEN-045, DEC-1328)', () => {
  it('names the product with one constant', () => {
    expect(PRODUCT_NAME).toBe('Overwatch');
  });

  it('is the product alone, with a page title in front of it', () => {
    expect(metadata.title).toEqual({ default: PRODUCT_NAME, template: `%s | ${PRODUCT_NAME}` });
  });

  it('never names an organisation, whichever host the page is served on', () => {
    const title = JSON.stringify(metadata.title);
    expect(title).not.toMatch(/Sample Area|Fortrus|Dorset/i);
  });

  it('has a description that is neutral: no place, organisation, service or system name', () => {
    const description = String(metadata.description);
    expect(description).toBeTruthy();
    expect(description).not.toMatch(/dorset|trust|spoa|single point|nhs|icb|systmone|Sample/i);
  });

  it('keeps the language en-GB, which is the default of every tenant profile', () => {
    expect(RootLayout({ children: null }).props.lang).toBe('en-GB');
  });
});

describe('root layout back-forward cache guard (TEN-050)', () => {
  it('mounts the guard on every page, so a page restored after sign-out is reloaded', async () => {
    const { BfcacheGuard } = await import('@/components/session/BfcacheGuard');
    const tree = RootLayout({ children: null });
    const body = tree.props.children as { props: { children: unknown[] } };
    const children = ([] as unknown[]).concat(body.props.children);
    expect(children.some((child) => (child as { type?: unknown })?.type === BfcacheGuard)).toBe(true);
  });
});

describe('root layout telemetry (W9F)', () => {
  it('mounts the telemetry on every page: it decides for itself whether a person is signed in', async () => {
    const { Telemetry } = await import('./Telemetry');
    const tree = RootLayout({ children: null });
    const body = tree.props.children as { props: { children: unknown[] } };
    const children = ([] as unknown[]).concat(body.props.children);
    expect(children.some((child) => (child as { type?: unknown })?.type === Telemetry)).toBe(true);
  });
});
