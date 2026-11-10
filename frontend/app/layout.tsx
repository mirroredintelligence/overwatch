import type { Metadata, Viewport } from 'next';
import { Atkinson_Hyperlegible } from 'next/font/google';
import type { ReactNode } from 'react';
import { LaunchSplash } from '@/components/brand/LaunchSplash';
import { RegisterServiceWorker } from '@/components/pwa/RegisterServiceWorker';
import { BfcacheGuard } from '@/components/session/BfcacheGuard';
import { InlineStyles } from '@/components/ui/InlineStyles';
import { PRODUCT_NAME } from '@/lib/product';
import { Telemetry } from './Telemetry';
import './tokens.css';
import './attention.css';
import './skeleton.css';

// Every page is rendered per request, so Next.js can put this request's nonce on its scripts (S01).
export const dynamic = 'force-dynamic';

const atkinson = Atkinson_Hyperlegible({
  subsets: ['latin'],
  weight: ['400', '700'],
  variable: '--font-atkinson',
  display: 'swap',
});

// The head names the product and no organisation (TEN-045, DEC-1328). Every staff sign-in is on one
// domain, so the host cannot say which organisation a visitor belongs to before sign-in; a host's
// profile name would leak one organisation's name to everyone. The organisation is shown inside the
// signed-in shell instead. The description is the same for everyone.
export const metadata: Metadata = {
  title: { default: PRODUCT_NAME, template: `%s | ${PRODUCT_NAME}` },
  description: 'Urgent-care capacity',
  manifest: '/manifest.webmanifest',
  appleWebApp: { capable: true, title: 'Overwatch', statusBarStyle: 'default' },
};

export const viewport: Viewport = {
  themeColor: '#0B5C8C',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en-GB" className={atkinson.variable}>
      <body>
        <InlineStyles />
        <BfcacheGuard />
        <Telemetry />
        {children}
        <RegisterServiceWorker />
        <LaunchSplash />
      </body>
    </html>
  );
}
