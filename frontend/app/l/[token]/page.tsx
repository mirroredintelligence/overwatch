import type { Metadata } from 'next';
import { LinkExpired } from '@/components/reporter/LinkExpired';
import { LinkLoader } from '@/components/reporter/LinkLoader';

// The capacity link page, opened from a text or an email. It holds a bearer token in its address,
// so: the page reads the link only through its own BFF (a press is the only thing that posts); it
// loads nothing from any other origin; it asks the browser not to send its address as a referrer;
// and it is never cached or indexed. An expired, used or unknown link shows the same message.
//
// The page itself reads nothing: the browser's own request to the BFF reads the link, because only
// a response to the browser can set the link's CSRF cookie (Next.js allows cookie writes only in
// Server Actions and Route Handlers), and one back-end read per view keeps the link budget
// (DEC-167 item 8) for the reporters who need it.

export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
  title: 'DIUCS capacity update',
  referrer: 'no-referrer',
  robots: { index: false, follow: false },
};

const TOKEN_SHAPE = /^[A-Za-z0-9_-]{1,64}$/;

export default async function LinkPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  // A token that cannot be a link is an unknown link: the same message, with no request made.
  if (!TOKEN_SHAPE.test(token)) return <LinkExpired token={token} csrfToken={null} />;
  return <LinkLoader token={token} />;
}
