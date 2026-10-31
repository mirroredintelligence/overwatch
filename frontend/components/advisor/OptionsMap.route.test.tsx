import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { OptionView } from '@/lib/advisor/options';
import { byEl } from '@/test/el';
import { MAP_VIEW } from '@/test/fixtures/map';
import { OptionsMap } from './OptionsMap';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

const OPTIONS = MAP_VIEW.options as unknown as OptionView[];

function draw(selectedId: string | null, onSelect = vi.fn()) {
  return render(
    <OptionsMap caseId="4821" postcode="DT4 8XX" patientArea={MAP_VIEW.patientArea} options={OPTIONS} selectedId={selectedId} onSelect={onSelect} onCriteria={vi.fn()} />,
  );
}

// What MapWeb and MapPhone show that the first map did not: a status shape on each pin, a button for each
// visiting area, the dotted route to the selected site, and the criteria version on the card.

describe('OptionsMap: pins, areas and the route (MapWeb 1, MapPhone 2)', () => {
  it('each pin carries a status shape as well as the name', () => {
    draw(null);
    const pin = byEl('ADV-MAP-PIN-SVC-UCR-WEST');
    expect(pin.querySelector('svg[data-shape], svg')).not.toBeNull();
    expect(pin).toHaveTextContent('UCR West');
  });

  it('a visiting area is a button named “(visits)” that selects its service, and the card shows', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    draw(null, onSelect);
    const area = byEl('ADV-MAP-AREA-SVC-HOSPITAL-AT-HOME');
    expect(area).toHaveAccessibleName('Hospital at home (visits)');
    await user.click(area);
    expect(onSelect).toHaveBeenCalledWith('svc-hospital-at-home');
  });

  it('draws the dotted route from the patient to a selected fixed site, and none for a visiting service', () => {
    const { container, rerender } = draw('svc-ward-b');
    const route = container.querySelector('[data-el="ADV-MAP-ROUTE"]');
    expect(route).not.toBeNull();
    expect(route?.getAttribute('stroke-dasharray')).toBe('2 8');

    rerender(
      <OptionsMap caseId="4821" postcode="DT4 8XX" patientArea={MAP_VIEW.patientArea} options={OPTIONS} selectedId="svc-hospital-at-home" onSelect={vi.fn()} />,
    );
    expect(container.querySelector('[data-el="ADV-MAP-ROUTE"]')).toBeNull();
  });

  it('draws no route before anything is selected, or with no patient place', () => {
    const none = draw(null);
    expect(none.container.querySelector('[data-el="ADV-MAP-ROUTE"]')).toBeNull();
    none.unmount();
    const noPatient = render(
      <OptionsMap caseId="4821" postcode="DT4 8XX" patientArea={null} options={OPTIONS} selectedId="svc-ward-b" onSelect={vi.fn()} />,
    );
    expect(noPatient.container.querySelector('[data-el="ADV-MAP-ROUTE"]')).toBeNull();
  });

  it('the caption names the route, and the card shows the criteria version', () => {
    draw('svc-ucr-west');
    expect(screen.getByText(/The dotted line is the route to the selected site\./)).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'UCR West' })).getByText('Criteria version 3')).toBeInTheDocument();
  });
});
