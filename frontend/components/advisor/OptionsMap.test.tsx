import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { MAP_VIEW } from '@/test/fixtures/map';
import { OptionsMap } from './OptionsMap';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

function renderMap(onSelect = vi.fn()) {
  render(
    <OptionsMap
      caseId="4821"
      postcode="DT4 8XX"
      patientArea={MAP_VIEW.patientArea}
      options={MAP_VIEW.options}
      selectedId={null}
      onSelect={onSelect}
      onRequest={vi.fn()}
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
        options={MAP_VIEW.options}
        selectedId={null}
        onSelect={vi.fn()}
        onRequest={vi.fn()}
        onCriteria={vi.fn()}
      />,
    );
    expect(screen.getByText('Patient area')).toBeInTheDocument();
    const pins = container.querySelectorAll('[data-el^="ADV-MAP-PIN-"]');
    expect(pins).toHaveLength(MAP_VIEW.options.filter((option) => option.position !== null).length);
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
        options={MAP_VIEW.options}
        selectedId={null}
        onSelect={vi.fn()}
        onRequest={vi.fn()}
        onCriteria={vi.fn()}
      />,
    );
    expect(container.querySelectorAll('circle[stroke-dasharray]')).toHaveLength(
      MAP_VIEW.options.filter((option) => option.coverage !== null).length,
    );
    expect(
      screen.getByText('Patient shown at postcode centre. Dashed areas are where a visiting service can attend.'),
    ).toBeInTheDocument();
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
        options={MAP_VIEW.options}
        selectedId="svc-ucr-west"
        onSelect={vi.fn()}
        onRequest={vi.fn()}
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
        options={MAP_VIEW.options}
        selectedId="svc-other-unit"
        onSelect={vi.fn()}
        onRequest={vi.fn()}
        onCriteria={vi.fn()}
      />,
    );
    const card = screen.getByRole('region', { name: 'Other unit' });

    expect(within(card).getByText('Neighbouring')).toBeInTheDocument();
    expect(within(card).queryByRole('button', { name: 'Request booking' })).toBeNull();
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <main>
        <OptionsMap
          caseId="4821"
          postcode="DT4 8XX"
          patientArea={MAP_VIEW.patientArea}
          options={MAP_VIEW.options}
          selectedId="svc-ucr-west"
          onSelect={vi.fn()}
          onRequest={vi.fn()}
          onCriteria={vi.fn()}
        />
      </main>,
    );
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
