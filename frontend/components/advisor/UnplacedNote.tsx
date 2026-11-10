import type { OptionView } from '@/lib/advisor/options';

// The services the picture cannot place (DEC-1360): a service with no site position and no covered district
// the locator can place has no point to draw, so the picture says so in words instead of leaving it out.
// A lead records a place by setting the districts the service covers (the coverage page).

export function unplacedOf(options: OptionView[]): OptionView[] {
  return options.filter((option) => option.position === null && option.coverage === null);
}

export function UnplacedNote({ options, className }: { options: OptionView[]; className?: string }) {
  const unplaced = unplacedOf(options);
  if (unplaced.length === 0) return null;
  const names = unplaced.map((option) => option.name).join(', ');
  return (
    <p className={className} data-el="ADV-MAP-UNPLACED">
      {unplaced.length === 1
        ? `Not drawn: ${names} has no place or covered districts recorded. It is in the list.`
        : `Not drawn: ${names} have no place or covered districts recorded. They are in the list.`}
    </p>
  );
}
