import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { RADAR_PARTS, UCR_FAR } from '@/test/fixtures/radar';
import type { Layer } from '@/lib/radar/radar';
import { RadarMap } from './RadarMap';

const ALL: ReadonlySet<Layer> = new Set<Layer>(['visiting', 'home', 'places']);

function renderMap(layers: ReadonlySet<Layer> = ALL, options = RADAR_PARTS.options) {
  return render(<RadarMap options={options} patientArea={RADAR_PARTS.patientArea} layers={layers} postcode="DT4 8XX" />);
}

describe('RadarMap', () => {
  it('draws a dashed area for each visiting service and hatches where two share ground', () => {
    const { container } = renderMap();
    expect(container.querySelectorAll('circle[stroke-dasharray]')).toHaveLength(3);
    // Three areas that all overlap give three pairs, each drawn hatched.
    expect(container.querySelectorAll('[data-el="RADAR-OVERLAP"]')).toHaveLength(3);
    expect(container.querySelector('pattern')).not.toBeNull();
  });

  it('draws no hatching for areas that share no ground', () => {
    const { container } = renderMap(ALL, [RADAR_PARTS.options[0], UCR_FAR]);
    expect(container.querySelectorAll('circle[stroke-dasharray]')).toHaveLength(2);
    expect(container.querySelectorAll('[data-el="RADAR-OVERLAP"]')).toHaveLength(0);
  });

  it('turning a layer off removes its drawing but not its entry in the list', () => {
    const { container } = renderMap(new Set<Layer>(['places']));
    expect(container.querySelectorAll('circle[stroke-dasharray]')).toHaveLength(0);
    expect(container.querySelectorAll('[data-el="RADAR-OVERLAP"]')).toHaveLength(0);
    const picture = byEl('RADAR-PICTURE');
    expect(within(picture).getByText('Community hospital · Ward B')).toBeInTheDocument();
    expect(within(picture).queryByText('UCR West')).toBeNull();
    // The list says it all in words, whatever is drawn.
    const list = screen.getByRole('list', { name: 'Services near DT4 8XX' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(4);
    expect(within(list).getAllByRole('listitem')[0]).toHaveTextContent('UCR West: Visits, area radius about 12 km');
  });

  it('labels the patient area and says the picture is a schematic', () => {
    renderMap();
    expect(screen.getByText('Patient area')).toBeInTheDocument();
    expect(screen.getByText(/Schematic, not to scale/)).toBeInTheDocument();
  });

  it('marks each service with its status shape, so the state is not carried by colour', () => {
    const { container } = renderMap();
    expect(byEl('RADAR-PICTURE').querySelectorAll('svg[aria-hidden="true"]').length).toBeGreaterThan(1);
    expect(container.querySelectorAll('span[class*="label"] svg')).toHaveLength(4);
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <main>
        <RadarMap options={RADAR_PARTS.options} patientArea={RADAR_PARTS.patientArea} layers={ALL} postcode="DT4 8XX" />
      </main>,
    );
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
