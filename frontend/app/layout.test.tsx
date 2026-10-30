import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// next/font/google fetches the font at build time, so the test replaces it with
// a stub that records the options the layout passes.
const atkinson = vi.hoisted(() => ({
  Atkinson_Hyperlegible: vi.fn(() => ({ className: 'atkinson-class', variable: 'atkinson-var' })),
}));
vi.mock('next/font/google', () => atkinson);

import { PRODUCT_NAME } from '@/lib/product';
import { resetProfileCache } from '@/lib/tenant/profile';
import { resetCookieWrites, setRequestHost } from '@/test/cookies';
import { BACKEND_ROOT } from '@/test/fixtures/links';
import { TENANTS } from '@/test/tenants';
import RootLayout, { generateMetadata } from './layout';

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


// TEN-045 and TEN-049: the page title and description name the product, never a place or a service of
// their own; the organisation's own name, when the host has a profile, comes from the profile.
describe('root layout metadata (TEN-045, TEN-049)', () => {
  beforeEach(() => {
    vi.stubEnv('DIUCS_FHIR_BASE_URL', `${BACKEND_ROOT}/fhir`);
    resetCookieWrites();
    resetProfileCache();
  });
  afterEach(() => vi.unstubAllEnvs());

  it('names the product with one constant', () => {
    expect(PRODUCT_NAME).toBe('DIUCS capacity');
  });

  it('puts the organisation name before the product in the title, for the host the page is served on', async () => {
    setRequestHost(TENANTS.A.host);
    const metadata = await generateMetadata();
    expect(metadata.title).toEqual({
      default: `Sample Area A | ${PRODUCT_NAME}`,
      template: `%s | Sample Area A | ${PRODUCT_NAME}`,
    });
  });

  it('puts another organisation’s name for another host, and never the first’s', async () => {
    setRequestHost(TENANTS.B.host);
    const title = JSON.stringify((await generateMetadata()).title);
    expect(title).toContain('Sample Area B');
    expect(title).not.toContain('Sample Area A');
  });

  it('is the product alone for a host nobody owns, or when the profile cannot be read', async () => {
    setRequestHost('nobody.example.test');
    expect((await generateMetadata()).title).toEqual({ default: PRODUCT_NAME, template: `%s | ${PRODUCT_NAME}` });
  });

  it('has a description that is neutral: no place, organisation, service or system name', async () => {
    setRequestHost(TENANTS.A.host);
    const description = String((await generateMetadata()).description);
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
    const { Telemetry } = await import('@/components/telemetry/Telemetry');
    const tree = RootLayout({ children: null });
    const body = tree.props.children as { props: { children: unknown[] } };
    const children = ([] as unknown[]).concat(body.props.children);
    expect(children.some((child) => (child as { type?: unknown })?.type === Telemetry)).toBe(true);
  });
});
