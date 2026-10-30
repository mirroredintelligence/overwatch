import { redirect } from 'next/navigation';
import { getSession } from '@/lib/auth/session';

// The app's front door (W35, W8E). With no signed-in reporter, the PIN screen. With one service, its
// update. With two or more, the grouped update (W38). With none (no live post), the list of services,
// which says how to add one, so the PIN screen is not shown again to someone who has just signed in.
export const dynamic = 'force-dynamic';

export default async function AppHome() {
  const session = await getSession();
  if (session === null || session.role !== 'reporter') redirect('/app/pin');
  if (session.services.length >= 2) redirect('/app/update');
  if (session.services.length === 1) redirect(`/app/respond/${encodeURIComponent(session.services[0])}`);
  redirect('/app/services');
}
