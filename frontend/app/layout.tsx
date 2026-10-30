import type { Metadata, Viewport } from 'next';
import { Atkinson_Hyperlegible } from 'next/font/google';
import type { ReactNode } from 'react';
import { RegisterServiceWorker } from '@/components/pwa/RegisterServiceWorker';
import { BfcacheGuard } from '@/components/session/BfcacheGuard';
import { Telemetry } from '@/components/telemetry/Telemetry';
import { PRODUCT_NAME } from '@/lib/product';
import { currentProfile } from '@/lib/tenant/profile';
import './tokens.css';

// Every page is rendered per request, so Next.js can put this request's nonce on its scripts (S01).
export const dynamic = 'force-dynamic';

const atkinson = Atkinson_Hyperlegible({
  subsets: ['latin'],
  weight: ['400', '700'],
  variable: '--font-atkinson',
  display: 'swap',
});

// The head names the product and no place of its own (TEN-045). The organisation's name, when the
// host has a profile, comes from the profile (TEN-049): "<organisation> | DIUCS capacity", and a page's
// own title goes in front. With no profile (an unknown host, a back end that is down) it is the
// product alone. The description is the same for everyone.
export async function generateMetadata(): Promise<Metadata> {
  const name = (await currentProfile())?.displayName;
  const tail = name === undefined ? PRODUCT_NAME : `${name} | ${PRODUCT_NAME}`;
  return {
    title: { default: tail, template: `%s | ${tail}` },
    description: 'Urgent-care capacity',
    manifest: '/manifest.webmanifest',
    appleWebApp: { capable: true, title: 'DIUCS', statusBarStyle: 'default' },
  };
}

export const viewport: Viewport = {
  themeColor: '#0B5C8C',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en-GB" className={atkinson.variable}>
      <body>
        <BfcacheGuard />
        <Telemetry />
        {children}
        <RegisterServiceWorker />
      </body>
    </html>
  );
}
