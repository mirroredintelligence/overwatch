import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { runAxe } from '@/test/a11y';
import { byEl } from '@/test/el';
import { RADAR_PARTS, UCR_FAR } from '@/test/fixtures/radar';
import { OptionsMap } from './OptionsMap';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

// The one Map view, with the "Who covers this area" layer (DEC-1372). jsdom has no WebGL, so these are the
// schematic's drawings; the tile map takes the same props and the same data.

function renderMap(props: Partial<React.ComponentProps<typeof OptionsMap>> = {}) {
  return render(
    <OptionsMap
      caseId="4821"
      postcode="DT4 8XX"
      patientArea={RADAR_PARTS.patientArea}
      options={RADAR_PARTS.options}
      selectedId={null}
      onSelect={vi.fn()}
      {...props}
    />,
  );
}

const areas = (container: HTMLElement) => container.querySelectorAll('[data-el^="ADV-MAP-COVER-AREA-"]');
const overlaps = (container: HTMLElement) => container.querySelectorAll('[data-el="ADV-MAP-COVER-OVERLAP"]');

describe('the coverage layer', () => {
  it('is a toggle, off by default, that adds the key and who covers the district', async () => {
    const { container } = renderMap();
    const toggle = screen.getByRole('button', { name: 'Who covers this area' });
    expect(toggle).toHaveAttribute('aria-pressed', 'false');
    expect(screen.queryByRole('heading', { name: 'Key' })).toBeNull();
    expect(overlaps(container)).toHaveLength(0);

    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('heading', { name: 'Key' })).toBeInTheDocument();
    expect(byEl('RADAR-SUMMARY')).toHaveTextContent('This patient is covered by 3 services.');
    expect(within(byEl('RADAR-COVERING')).getByText('UCR West')).toBeInTheDocument();
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-pressed', 'false');
    expect(screen.queryByRole('heading', { name: 'Key' })).toBeNull();
  });

  it('starts on when the address asked for it', () => {
    renderMap({ initialCoverage: true });
    expect(screen.getByRole('button', { name: 'Who covers this area' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('heading', { name: 'Key' })).toBeInTheDocument();
  });

  it('outlines each visiting area by line and hatches where two share ground', () => {
    const { container } = renderMap({ initialCoverage: true });
    const [first, second] = Array.from(areas(container));
    expect(areas(container)).toHaveLength(3);
    expect(first).not.toHaveAttribute('stroke-dasharray');
    expect(second).toHaveAttribute('stroke-dasharray');
    expect(first.getAttribute('stroke')).not.toEqual(second.getAttribute('stroke'));
    expect(overlaps(container)).toHaveLength(3);
    expect(container.querySelector('pattern')).not.toBeNull();
  });

  it('hatches nothing for areas that share no ground', () => {
    const { container } = renderMap({ initialCoverage: true, options: [RADAR_PARTS.options[0], UCR_FAR] });
    expect(areas(container)).toHaveLength(2);
    expect(overlaps(container)).toHaveLength(0);
  });

  it('keeps the places to go as pins, and no drive-time or traffic wording anywhere', () => {
    const { container } = renderMap({ initialCoverage: true });
    expect(byEl('ADV-MAP-PIN-SVC-WARD-B')).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/drive-time|traffic/i);
  });

  it('says who covers cannot be worked out when the patient location is not known', () => {
    renderMap({ initialCoverage: true, patientArea: null });
    expect(byEl('RADAR-SUMMARY')).toHaveTextContent(/location is not known/i);
    expect(byEl('RADAR-SUMMARY')).not.toHaveTextContent(/No visiting service covers/);
  });

  it('has no axe violations with the layer on', async () => {
    const { container } = render(
      <main>
        <OptionsMap caseId="4821" postcode="DT4 8XX" patientArea={RADAR_PARTS.patientArea} options={RADAR_PARTS.options} selectedId={null} onSelect={vi.fn()} initialCoverage />
      </main>,
    );
    expect((await runAxe(container)).violations).toEqual([]);
  });
});

describe('the patient marker and the words under the map', () => {
  it('draws "Patient area · <outward code>" when the location is known, never the full postcode', () => {
    const { container } = renderMap();
    expect(screen.getByText('Patient area · DT4')).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/8XX/);
    expect(screen.getByText(/patient's area is marked at the postcode centre/i)).toBeInTheDocument();
  });

  it('draws nothing for the patient, and says nothing about one, when the location is not known', () => {
    const { container } = renderMap({ patientArea: null });
    expect(screen.queryByText(/Patient area/)).toBeNull();
    expect(container.querySelector('[class*="patient"]')).toBeNull();
    expect(container.textContent).not.toMatch(/patient/i);
    expect(screen.getByText(/Dashed areas are where a visiting service can attend/)).toBeInTheDocument();
  });

  it('labels with the bare words when the postcode is not an outward code', () => {
    renderMap({ postcode: 'Weymouth' });
    expect(screen.getByText('Patient area')).toBeInTheDocument();
  });
});
