import type { Metadata } from 'next';
import { Atkinson_Hyperlegible } from 'next/font/google';
import type { ReactNode } from 'react';
import { BfcacheGuard } from '@/components/session/BfcacheGuard';
import { PRODUCT_NAME } from '@/lib/product';
import './tokens.css';

// Every page is rendered per request, so Next.js can put this request's nonce on its scripts (S01).
export const dynamic = 'force-dynamic';

const atkinson = Atkinson_Hyperlegible({
  subsets: ['latin'],
  weight: ['400', '700'],
  variable: '--font-atkinson',
  display: 'swap',
});

// The head names the product and no place (TEN-045): a page's own title is put in the template, and an
// organisation's own name comes from its profile (TEN-049).
export const metadata: Metadata = {
  title: { default: PRODUCT_NAME, template: `%s | ${PRODUCT_NAME}` },
  description: 'Urgent-care capacity',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en-GB" className={atkinson.variable}>
      <body>
        <BfcacheGuard />
        {children}
      </body>
    </html>
  );
}
