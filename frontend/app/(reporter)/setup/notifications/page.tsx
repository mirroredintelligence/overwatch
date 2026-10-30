import { Notifications } from '@/components/reporter/setup/Notifications';

export const dynamic = 'force-dynamic';

// The service name comes from the set-up summary, which the all-set step reads; until the back end
// serves it, the consent text names the service the reporter was invited to.
export default function NotificationsPage() {
  return <Notifications service="your service" />;
}
