import { PhoneLink } from '@/components/scope/PhoneLink';
import type { OptionView } from '@/lib/advisor/options';

// The service line of a network service (docs/design/network-ui.md section 4, WB11): the one thing an advisor
// does with another organisation's row is phone the service, so the number is a link, named for the service
// ("Phone UCR West on 01632 960010"), and a service that shared none says so. The own organisation's services
// have no such row: they carry the booking panel of the case.

export function NetworkServiceLine({ option, className }: { option: Pick<OptionView, 'name' | 'phone'>; className?: string }) {
  return option.phone === null ? (
    <p className={className}>No number shared</p>
  ) : (
    <p className={className}>
      {'Service line '}
      <PhoneLink serviceName={option.name} phone={option.phone} dataEl="NET-BOARD-PHONE-LINK" />
    </p>
  );
}
