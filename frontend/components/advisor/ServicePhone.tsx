import { Button } from '@/components/ui/Button';
import styles from './ServiceCard.module.css';

// The number to phone a service (Q5, KI-626): the one the back end holds for it, as a link. A service with
// none says so and points to the advisor's own directory; a number is never made up or looked up here.

export const NO_PHONE_HELD = 'No phone number is held for this service. Find it in your service directory.';

export function ServicePhone({ phone }: { phone: string | null }) {
  if (phone === null) return <p className={styles.line}>{NO_PHONE_HELD}</p>;
  return (
    <Button variant="secondary" href={`tel:${phone}`} dataEl="ADV-OPT-PHONE-LINK">
      {`Phone ${phone}`}
    </Button>
  );
}
