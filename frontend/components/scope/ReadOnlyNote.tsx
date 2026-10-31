import { Banner } from '@/components/ui/Banner';

// Shown once above the rows of a network view, never on every row (docs/design/network-ui.md section 3):
// the rows have no button but the service line link.
export function ReadOnlyNote() {
  return (
    <Banner tone="info" title="Read only" dataEl="SCOPE-READONLY-NOTE">
      You cannot book or change these services from here. Phone the service to check.
    </Banner>
  );
}
