import type { Metadata } from 'next';
import { Atkinson_Hyperlegible } from 'next/font/google';
import type { ReactNode } from 'react';
import './tokens.css';

// Every page is rendered per request, so Next.js can put this request's nonce on its scripts (S01).

// Every page is rendered per request, so Next.js can put this request's nonce on its scripts (S01).
export const dynamic = 'force-dynamic';

const atkinson = Atkinson_Hyperlegible({
  subsets: ['latin'],
  weight: ['400', '700'],
  variable: '--font-atkinson',
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'DIUCS capacity',
  description: 'Urgent-care capacity for the single point of access',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en-GB" className={atkinson.variable}>
      <body>{children}</body>
    </html>
  );
}
