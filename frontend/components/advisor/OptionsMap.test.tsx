import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { MAP_VIEW } from '@/test/fixtures/map';
import type { OptionView } from '@/lib/advisor/options';

// The fixture is plain JSON; the view type is the one the BFF answers (W13, W50).
const MAP_OPTIONS = MAP_VIEW.options as unknown as OptionView[];
import { OptionsMap } from './OptionsMap';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

function renderMap(onSelect = vi.fn()) {
  render(
    <OptionsMap
      caseId="4821"
      postcode="DT4 8XX"
      patientArea={MAP_VIEW.patientArea}
      options={MAP_OPTIONS}
      selectedId={null}
      onSelect={onSelect}
      onCriteria={vi.fn()}
    />,
  );
  return { onSelect };
}

describe('OptionsMap (W50)', () => {
  it('draws the patient area and one pin button per fixed site, each with its name', () => {
    const { container } = render(
      <OptionsMap
        caseId="4821"
        postcode="DT4 8XX"
        patientArea={MAP_VIEW.patientArea}
        options={MAP_OPTIONS}
        selectedId={null}
        onSelect={vi.fn()}
        onCriteria={vi.fn()}
      />,
    );
    expect(screen.getByText('Patient area')).toBeInTheDocument();
    const pins = container.querySelectorAll('[data-el^="ADV-MAP-PIN-"]');
    expect(pins).toHaveLength(MAP_OPTIONS.filter((option) => option.position !== null).length);
    for (const pin of Array.from(pins)) {
      expect(pin.tagName).toBe('BUTTON');
      expect(pin.getAttribute('aria-label')).toBeTruthy();
    }
    expect(byEl('ADV-MAP-PIN-SVC-UCR-WEST')).toHaveAccessibleName('UCR West');
  });

  it('draws one dashed coverage area per visiting service, and no dashed area for the patient', () => {
    const { container } = render(
      <OptionsMap
        caseId="4821"
        postcode="DT4 8XX"
        patientArea={MAP_VIEW.patientArea}
        options={MAP_OPTIONS}
        selectedId={null}
        onSelect={vi.fn()}
        onCriteria={vi.fn()}
      />,
    );
    expect(container.querySelectorAll('circle[stroke-dasharray]')).toHaveLength(
      MAP_OPTIONS.filter((option) => option.coverage !== null).length,
    );
    expect(
      screen.getByText('Patient shown at postcode centre. Dashed areas are where a visiting service can attend. The dotted line is the route to the selected site.'),
    ).toBeInTheDocument();
  });

  it('says that drive-time rings and traffic are off, because there is no data behind them (Map board)', () => {
    renderMap();
    const note = screen.getByText(/Drive-time rings and traffic are/);
    expect(note).toHaveTextContent('Drive-time rings and traffic are off: there is no data behind them yet.');
  });

  it('each pin names the service and its free figure, with a status shape, so the status is not colour alone', () => {
    renderMap();
    const pin = byEl('ADV-MAP-PIN-SVC-UCR-WEST');
    expect(pin).toHaveTextContent('UCR West · 4');
    expect(pin).toHaveAttribute('data-status', 'accepting');
    expect(pin.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
    // A visiting service reads the same way, and keeps its “(visits)” name.
    expect(byEl('ADV-MAP-AREA-SVC-HOSPITAL-AT-HOME')).toHaveTextContent('Hospital at home (visits) · 3');
  });

  it('an over-capacity service shows how far over it is, as the board does (+2)', () => {
    const [first, ...rest] = MAP_OPTIONS;
    render(
      <OptionsMap
        caseId="4821"
        postcode="DT4 8XX"
        patientArea={MAP_VIEW.patientArea}
        options={[{ ...first, status: 'over-capacity', overBy: 2 }, ...rest]}
        selectedId={null}
        onSelect={vi.fn()}
      />,
    );
    expect(byEl('ADV-MAP-PIN-SVC-UCR-WEST')).toHaveTextContent('UCR West · +2');
    expect(byEl('ADV-MAP-PIN-SVC-UCR-WEST')).toHaveAttribute('data-status', 'over-capacity');
  });

  it('marks the selected pin as pressed, and only that one', () => {
    render(
      <OptionsMap caseId="4821" postcode="DT4 8XX" patientArea={MAP_VIEW.patientArea} options={MAP_OPTIONS} selectedId="svc-ward-b" onSelect={vi.fn()} />,
    );
    expect(byEl('ADV-MAP-PIN-SVC-WARD-B')).toHaveAttribute('aria-pressed', 'true');
    expect(byEl('ADV-MAP-PIN-SVC-UCR-WEST')).toHaveAttribute('aria-pressed', 'false');
  });

  it('selecting a pin reports its service, and shows its card with the travel range', async () => {
    const user = userEvent.setup();
    const { onSelect } = renderMap();

    await user.click(byEl('ADV-MAP-PIN-SVC-UCR-WEST'));

    expect(onSelect).toHaveBeenCalledWith('svc-ucr-west');
  });

  it('a selected pin shows its card: the free figure, the travel range, the age, and the three actions', () => {
    render(
      <OptionsMap
        caseId="4821"
        postcode="DT4 8XX"
        patientArea={MAP_VIEW.patientArea}
        options={MAP_OPTIONS}
        selectedId="svc-ucr-west"
        onSelect={vi.fn()}
        onCriteria={vi.fn()}
      />,
    );
    const card = screen.getByRole('region', { name: 'UCR West' });

    expect(within(card).getByText('Accepting')).toBeInTheDocument();
    expect(within(card).getByText('Free 4 referrals in the next 2 hrs')).toBeInTheDocument();
    expect(within(card).getByText('Patient to UCR West by road 35 to 50 min')).toBeInTheDocument();
    expect(within(card).getByText('Updated 9 min ago')).toBeInTheDocument();
    expect(within(card).getByRole('button', { name: 'Request booking' })).toBeInTheDocument();
    expect(within(card).getByRole('button', { name: 'Criteria' })).toBeInTheDocument();
    expect(byEl('ADV-MAP-TRAVEL-BTN', card)).toBeInTheDocument();
  });

  it('a network pin is view only: its card names the organisation and has no booking action', () => {
    render(
      <OptionsMap
        caseId="4821"
        postcode="DT4 8XX"
        patientArea={MAP_VIEW.patientArea}
        options={MAP_OPTIONS}
        selectedId="svc-other-unit"
        onSelect={vi.fn()}
        onCriteria={vi.fn()}
      />,
    );
    const card = screen.getByRole('region', { name: 'Other unit' });

    expect(within(card).getByText('Neighbouring')).toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: 'Request booking' })).toBeNull();
    expect(within(card).queryByRole('button', { name: 'Criteria' })).toBeNull();
  });

  it('a network pin has the criteria button only on the network map, and the service line in place of the phone button', async () => {
    const onNetworkCriteria = vi.fn();
    const withPhone = MAP_OPTIONS.map((option) => (option.network === null ? option : { ...option, phone: '01632 960010' }));
    render(
      <OptionsMap
        caseId="4821"
        postcode="DT4 8XX"
        patientArea={MAP_VIEW.patientArea}
        options={withPhone}
        selectedId="svc-other-unit"
        onSelect={vi.fn()}
        onNetworkCriteria={onNetworkCriteria}
      />,
    );
    const card = screen.getByRole('region', { name: 'Other unit' });

    await userEvent.click(within(card).getByRole('button', { name: 'Criteria' }));
    expect(onNetworkCriteria).toHaveBeenCalledWith('svc-other-unit');
    expect(within(card).getByRole('link', { name: 'Phone Other unit on 01632 960010' })).toHaveAttribute('data-el', 'NET-BOARD-PHONE-LINK');
    expect(within(card).getAllByRole('link')).toHaveLength(1);
  });

  it('a pin card with a service phone offers it as a link; one with none says so (Q5)', () => {
    const [first] = MAP_OPTIONS;
    render(
      <OptionsMap
        caseId="4821"
        postcode="DT4 8XX"
        patientArea={MAP_VIEW.patientArea}
        options={[{ ...first, phone: '01305 900100' }]}
        selectedId={first.serviceId}
        onSelect={vi.fn()}
        onCriteria={vi.fn()}
      />,
    );

    expect(screen.getByRole('link', { name: 'Phone 01305 900100' })).toHaveAttribute('href', 'tel:01305 900100');
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <main>
        <OptionsMap
          caseId="4821"
          postcode="DT4 8XX"
          patientArea={MAP_VIEW.patientArea}
          options={MAP_OPTIONS}
          selectedId="svc-ucr-west"
          onSelect={vi.fn()}
          onCriteria={vi.fn()}
        />
      </main>,
    );
    expect((await runAxe(container)).violations).toEqual([]);
  });
});


describe('the booking control on a pin card (W20, W50)', () => {
  it('is the booking panel of this case and the selected service', async () => {
    document.cookie = 'overwatch_csrf=csrf-value-for-the-map; path=/';
    const user = userEvent.setup();
    render(
      <OptionsMap
        caseId="case-1"
        postcode="DT4"
        patientArea={MAP_VIEW.patientArea}
        options={MAP_OPTIONS}
        selectedId="svc-ucr-west"
        onSelect={vi.fn()}
      />,
    );
    const card = screen.getByRole('region', { name: 'UCR West' });

    await user.click(within(card).getByRole('button', { name: 'Request booking' }));

    expect(await within(card).findByText('Requested')).toBeInTheDocument();
  });
});
