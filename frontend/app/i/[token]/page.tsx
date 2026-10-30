import { InvitationLoader } from '@/components/reporter/setup/InvitationLoader';

// The invitation link (W33). A token that cannot be an invitation is shown as expired, with no
// request made. Anything else is looked up by the loader, which redirects a valid one to /setup.

export const dynamic = 'force-dynamic';

const TOKEN_SHAPE = /^[A-Za-z0-9_-]{1,64}$/;

export default async function InvitationPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  if (!TOKEN_SHAPE.test(token)) {
    return (
      <main>
        <h1>This invitation has expired</h1>
        <p>This invitation has expired. Ask the shift lead to send a new one.</p>
      </main>
    );
  }
  return <InvitationLoader token={token} />;
}
