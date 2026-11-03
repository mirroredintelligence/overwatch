import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { RADAR_PARTS, UCR_FAR } from '@/test/fixtures/radar';
import { RadarMap } from './RadarMap';

function renderMap(options = RADAR_PARTS.options) {
  return render(<RadarMap options={options} patientArea={RADAR_PARTS.patientArea} postcode="DT4 8XX" />);
}

const areas = (container: HTMLElement) => container.querySelectorAll('[data-el^="RADAR-AREA-"]');

describe('RadarMap', () => {
  it('draws an area for each visiting service and hatches where two share ground', () => {
    const { container } = renderMap();
    expect(areas(container)).toHaveLength(3);
    // Three areas that all overlap give three pairs, each drawn hatched.
    expect(container.querySelectorAll('[data-el="RADAR-OVERLAP"]')).toHaveLength(3);
    expect(container.querySelector('pattern')).not.toBeNull();
  });

  it('draws the first area solid and the second dashed, so the two differ by line and not only by colour', () => {
    const { container } = renderMap();
    const [first, second] = Array.from(areas(container));
    expect(first).not.toHaveAttribute('stroke-dasharray');
    expect(second).toHaveAttribute('stroke-dasharray');
    expect(first.getAttribute('stroke')).not.toEqual(second.getAttribute('stroke'));
  });

  it('draws no hatching for areas that share no ground', () => {
    const { container } = renderMap([RADAR_PARTS.options[0], UCR_FAR]);
    expect(areas(container)).toHaveLength(2);
    expect(container.querySelectorAll('[data-el="RADAR-OVERLAP"]')).toHaveLength(0);
  });

  it('labels each place to go in the picture and lists every service in words', () => {
    renderMap();
    const picture = byEl('RADAR-PICTURE');
    expect(within(picture).getByText('Community hospital · Ward B')).toBeInTheDocument();
    const list = screen.getByRole('list', { name: 'Services near DT4 8XX' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(4);
    expect(within(list).getAllByRole('listitem')[0]).toHaveTextContent('UCR West: Visits, area radius about 12 km');
  });

  it('labels the patient at the postcode centre and says the picture is a schematic', () => {
    renderMap();
    expect(screen.getByText('Patient · DT4 8XX')).toBeInTheDocument();
    expect(screen.getByText(/Schematic, not to scale/)).toBeInTheDocument();
  });

  it('says that drive-time rings and traffic are off because there is no data behind them', () => {
    renderMap();
    expect(byEl('RADAR-OFF-NOTE')).toHaveTextContent('Drive-time rings and traffic are off because there is no data behind them yet.');
  });

  it('marks each service with its status shape, so the state is not carried by colour', () => {
    const { container } = renderMap();
    expect(byEl('RADAR-PICTURE').querySelectorAll('svg[aria-hidden="true"]').length).toBeGreaterThan(1);
    expect(container.querySelectorAll('span[class*="label"] svg')).toHaveLength(4);
  });

  it('has no axe violations', async () => {
    const { container } = render(
      <main>
        <RadarMap options={RADAR_PARTS.options} patientArea={RADAR_PARTS.patientArea} postcode="DT4 8XX" />
      </main>,
    );
    expect((await runAxe(container)).violations).toEqual([]);
  });
});
